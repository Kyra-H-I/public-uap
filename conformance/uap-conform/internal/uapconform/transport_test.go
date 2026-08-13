package uapconform

import (
	"bufio"
	"encoding/json"
	"net"
	"strings"
	"testing"
	"time"
)

// echoServer answers every request after optionally injecting noise frames, proving
// the peer correlates by id rather than by arrival order.
func echoServer(t *testing.T, conn net.Conn, noise []string) {
	t.Helper()
	reader := bufio.NewReader(conn)
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			return
		}
		var req map[string]any
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			t.Errorf("server got non-JSON: %v", err)
			return
		}
		for _, frame := range noise {
			if _, err := conn.Write([]byte(frame + "\n")); err != nil {
				return
			}
		}
		reply := map[string]any{"type": "uap.reply", "id": req["id"], "answered": req["type"]}
		out, _ := json.Marshal(reply)
		if _, err := conn.Write(append(out, '\n')); err != nil {
			return
		}
	}
}

func TestCallCorrelatesByIdAndSkipsNoise(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	noise := []string{
		`{"type": "uap.event", "provider": "x", "event": "view.changed", "seq": 1}`,
		`{"type": "uap.reply", "id": "somebody-else"}`,
	}
	go echoServer(t, server, noise)

	peer := NewWirePeer(client, client, time.Second)
	reply, err := peer.Call(TypeDescribe, map[string]any{})
	if err != nil {
		t.Fatal(err)
	}
	if asString(reply["answered"]) != TypeDescribe {
		t.Fatalf("wrong reply: %v", reply)
	}
}

func TestASilentProviderIsATimeoutNotAHang(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	peer := NewWirePeer(client, client, 50*time.Millisecond)
	done := make(chan error, 1)
	go func() {
		_, err := peer.Call(TypeDescribe, map[string]any{})
		done <- err
	}()
	// net.Pipe is synchronous, so the request must be consumed for Call to proceed
	// to the wait; the server then goes silent.
	reader := bufio.NewReader(server)
	if _, err := reader.ReadString('\n'); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "no reply") {
			t.Fatalf("err = %v, want timeout", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Call hung on a silent provider")
	}
}

func TestGarbageOnTheStreamIsTerminal(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()

	peer := NewWirePeer(client, client, time.Second)
	go func() {
		reader := bufio.NewReader(server)
		_, _ = reader.ReadString('\n')
		// A provider logging to stdout instead of stderr: corruption, not noise.
		_, _ = server.Write([]byte("INFO ready to serve\n"))
	}()
	if _, err := peer.Call(TypeDescribe, map[string]any{}); err == nil {
		t.Fatal("a non-JSON frame must be a terminal error")
	}
}

func TestAFrameOverTheCapIsTerminal(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()

	peer := NewWirePeer(client, client, 5*time.Second)
	go func() {
		reader := bufio.NewReader(server)
		_, _ = reader.ReadString('\n')
		huge := `{"pad": "` + strings.Repeat("x", maxFrameBytes+16) + `"}` + "\n"
		for len(huge) > 0 {
			n, err := server.Write([]byte(huge))
			if err != nil {
				return
			}
			huge = huge[n:]
		}
	}()
	_, err := peer.Call(TypeDescribe, map[string]any{})
	if err == nil {
		t.Fatal("an over-cap frame must be a terminal error, not a truncated parse")
	}
}
