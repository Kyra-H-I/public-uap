// uap-conform grades a UAP provider over the wire: it speaks the envelope dialect —
// line-delimited JSON — to a provider reached either by spawning a harness command
// (stdin/stdout) or by dialing a unix socket, runs the fourteen core conformance
// vectors, and prints the machine-readable report to stdout.
//
//	uap-conform -cmd "python path/to/your/stdio_harness.py"
//	uap-conform -socket /run/user/1000/provider.sock
//
// The report is the same shape as the reference Python suite's,
// so it feeds the same assurance decision. Exit codes: 0 = passed, 1 = one or more
// vectors failed, 2 = the provider could not be graded at all (transport or protocol
// error). The run is safe against a live application: reads and refusals only.
//
// A harness is ~20 lines in any language: read one JSON object per line, dispatch on
// "type", reply on stdout echoing "id" — and log to stderr, never stdout, because the
// stdout stream is the protocol.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"
	"os/exec"
	"time"

	"github.com/Kyra-H-I/public-uap/conformance/uap-conform/internal/uapconform"
)

func main() {
	os.Exit(run())
}

func run() int {
	cmdline := flag.String("cmd", "", "provider harness command, spoken to over stdin/stdout (via sh -c)")
	socket := flag.String("socket", "", "unix socket path of a running provider")
	timeout := flag.Duration("timeout", 10*time.Second, "per-request reply deadline")
	flag.Parse()

	if (*cmdline == "") == (*socket == "") {
		fmt.Fprintln(os.Stderr, "uap-conform: exactly one of -cmd or -socket is required")
		return 2
	}

	var peer *uapconform.WirePeer
	var cleanup func()
	if *cmdline != "" {
		child := exec.Command("sh", "-c", *cmdline)
		child.Stderr = os.Stderr // the provider's logs; stdout is the protocol
		stdin, err := child.StdinPipe()
		if err != nil {
			fmt.Fprintf(os.Stderr, "uap-conform: %v\n", err)
			return 2
		}
		stdout, err := child.StdoutPipe()
		if err != nil {
			fmt.Fprintf(os.Stderr, "uap-conform: %v\n", err)
			return 2
		}
		if err := child.Start(); err != nil {
			fmt.Fprintf(os.Stderr, "uap-conform: start %q: %v\n", *cmdline, err)
			return 2
		}
		peer = uapconform.NewWirePeer(stdout, stdin, *timeout)
		cleanup = func() {
			// Closing stdin is the harness's EOF signal; the kill is for one that
			// does not exit on it, so the runner never outlives its subject.
			_ = stdin.Close()
			done := make(chan struct{})
			go func() { _ = child.Wait(); close(done) }()
			select {
			case <-done:
			case <-time.After(2 * time.Second):
				_ = child.Process.Kill()
				<-done
			}
		}
	} else {
		conn, err := net.Dial("unix", *socket)
		if err != nil {
			fmt.Fprintf(os.Stderr, "uap-conform: dial %s: %v\n", *socket, err)
			return 2
		}
		peer = uapconform.NewWirePeer(conn, conn, *timeout)
		cleanup = func() { _ = conn.Close() }
	}
	defer cleanup()

	report, err := uapconform.RunCore(peer)
	if err != nil {
		fmt.Fprintf(os.Stderr, "uap-conform: %v\n", err)
		return 2
	}

	out, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "uap-conform: %v\n", err)
		return 2
	}
	fmt.Println(string(out))

	failures := report.Failures()
	fmt.Fprintf(os.Stderr, "uap-conform: %s — %d passed, %d failed, %d skipped\n",
		verdict(len(failures) == 0), len(report.Results)-len(failures)-len(report.Skipped()),
		len(failures), len(report.Skipped()))
	for _, f := range failures {
		fmt.Fprintf(os.Stderr, "  FAIL %s: %s\n", f.ID, f.Detail)
	}
	if len(failures) > 0 {
		return 1
	}
	return 0
}

func verdict(passed bool) string {
	if passed {
		return "PASSED"
	}
	return "FAILED"
}
