package uapconform

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"
)

// Peer is one provider endpoint the vectors can call. The wire implementation below is
// what the CLI uses; tests substitute an in-process fake, which is exactly the seam the
// Python suite gets from its provider object.
type Peer interface {
	Call(reqType string, body map[string]any) (map[string]any, error)
}

// maxFrameBytes bounds one NDJSON line. Same policy as the bridge relay's frame
// scanner: an over-long line is terminal for the connection, full stop, because a
// truncated frame that still parses is worse than no frame.
const maxFrameBytes = 1 << 20

// errFrameTooLarge mirrors the relay's over-cap policy for this package's own reader.
var errFrameTooLarge = errors.New("uapconform: frame over cap")

type readResult struct {
	payload map[string]any
	err     error
}

// WirePeer speaks the UAP envelope dialect over any byte stream: line-delimited JSON,
// requests stamped with a fresh id, replies correlated by that id, events skipped.
type WirePeer struct {
	w       io.Writer
	lines   chan readResult
	timeout time.Duration
}

// NewWirePeer starts reading frames from r immediately. One WirePeer supports one
// sequential caller — the conformance run is strictly sequential, as is the Python
// suite, so requests never overlap.
func NewWirePeer(r io.Reader, w io.Writer, timeout time.Duration) *WirePeer {
	p := &WirePeer{w: w, lines: make(chan readResult), timeout: timeout}
	go p.readLoop(r)
	return p
}

func (p *WirePeer) readLoop(r io.Reader) {
	reader := bufio.NewReaderSize(r, 64*1024)
	for {
		line, err := readBoundedLine(reader)
		if err != nil {
			p.lines <- readResult{err: err}
			return
		}
		if len(line) == 0 {
			continue
		}
		var payload map[string]any
		if err := json.Unmarshal(line, &payload); err != nil {
			// A stream that is not JSON is corruption, not noise — a provider logging
			// to stdout instead of stderr must hear about it, not be half-parsed.
			p.lines <- readResult{err: fmt.Errorf("uapconform: non-JSON frame: %w", err)}
			return
		}
		p.lines <- readResult{payload: payload}
	}
}

// readBoundedLine reads one \n-terminated line with a hard cap. Written by hand for
// the same reason as the relay's frame scanner: bufio.Scanner leaves the rest of an
// over-long line in the stream, and resuming mid-frame produces garbage that still
// parses often enough to be dangerous.
func readBoundedLine(reader *bufio.Reader) ([]byte, error) {
	var line []byte
	for {
		chunk, err := reader.ReadSlice('\n')
		line = append(line, chunk...)
		if len(line) > maxFrameBytes {
			return nil, errFrameTooLarge
		}
		if err == nil {
			return line[:len(line)-1], nil
		}
		if errors.Is(err, bufio.ErrBufferFull) {
			continue
		}
		return nil, err
	}
}

// Call sends one request and waits for the reply that echoes its id, dropping events
// and unsolicited frames along the way. A silent provider is a timeout error, never an
// indefinite wait.
func (p *WirePeer) Call(reqType string, body map[string]any) (map[string]any, error) {
	id := newID()
	envelope := make(map[string]any, len(body)+2)
	for key, value := range body {
		envelope[key] = value
	}
	envelope["type"] = reqType
	envelope["id"] = id

	frame, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("uapconform: marshal %s: %w", reqType, err)
	}
	if _, err := p.w.Write(append(frame, '\n')); err != nil {
		return nil, fmt.Errorf("uapconform: write %s: %w", reqType, err)
	}

	deadline := time.NewTimer(p.timeout)
	defer deadline.Stop()
	for {
		select {
		case res := <-p.lines:
			if res.err != nil {
				return nil, res.err
			}
			if asString(res.payload["type"]) == TypeEvent {
				continue // events are legitimate at any time; the core run ignores them
			}
			if asString(res.payload["id"]) == id {
				return res.payload, nil
			}
			// A reply to something this runner never asked: drop it, keep waiting.
		case <-deadline.C:
			return nil, fmt.Errorf("uapconform: no reply to %s within %s", reqType, p.timeout)
		}
	}
}

func newID() string {
	var buf [16]byte
	if _, err := rand.Read(buf[:]); err != nil {
		// crypto/rand failing is a broken platform; ids only need uniqueness within
		// one run, so panicking beats silently reusing an id.
		panic(fmt.Sprintf("uapconform: rand: %v", err))
	}
	return hex.EncodeToString(buf[:])
}
