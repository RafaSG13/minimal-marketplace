package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	stopWait  = 5 * time.Second // how long a server told to quit may take before it is killed
	drainWait = time.Second     // how long the output of an exited server may take to be read
	tailBytes = 2048            // how much of the server's stderr is shown when it fails
)

// serverExit is delivered to the interface when the server process has ended.
type serverExit struct{ code int }

// server is the `minimal serve` child: lines out to its stdin, lines in from its stdout, stderr in a log file.
type server struct {
	cmd  *exec.Cmd
	conn *conn

	stdin   io.Closer
	stdout  *os.File // read end of the child's stdout
	log     *os.File
	logPath string
	keepLog bool // the log was asked for with MINIMAL_GO_LOG: it is never removed

	read   chan struct{} // closed when stdout has been read to its end
	done   chan struct{} // closed when the process has exited; code is set by then
	code   int
	killed bool
}

// startServer runs `bin serve args...`. Its stderr must not reach the terminal the interface draws on, so it goes
// to the file named by MINIMAL_GO_LOG, else to a log of this run in the user's cache directory.
func startServer(bin string, args []string) (*server, error) {
	log, path, keep, err := openLog()
	if err != nil {
		return nil, err
	}
	rd, wr, err := os.Pipe()
	if err != nil {
		log.Close()
		return nil, err
	}
	cmd := exec.Command(bin, append([]string{"serve"}, args...)...)
	cmd.Stdout, cmd.Stderr = wr, log
	stdin, err := cmd.StdinPipe()
	if err != nil {
		rd.Close()
		wr.Close()
		log.Close()
		return nil, err
	}
	err = cmd.Start()
	wr.Close() // the child holds the write end now
	if err != nil {
		rd.Close()
		log.Close()
		os.Remove(path)
		return nil, err
	}
	return &server{
		cmd: cmd, conn: &conn{out: stdin}, stdin: stdin, stdout: rd, log: log, logPath: path, keepLog: keep,
		read: make(chan struct{}), done: make(chan struct{}),
	}, nil
}

// openLog creates the file the server's stderr goes to.
func openLog() (f *os.File, path string, keep bool, err error) {
	if path = os.Getenv("MINIMAL_GO_LOG"); path != "" {
		f, err = os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		return f, path, true, err
	}
	dir, err := os.UserCacheDir()
	if err == nil {
		dir = filepath.Join(dir, "minimal-go")
		err = os.MkdirAll(dir, 0o755)
	}
	if err != nil {
		dir = os.TempDir()
	}
	f, err = os.CreateTemp(dir, "serve-*.log")
	if err != nil {
		return nil, "", false, err
	}
	return f, f.Name(), false, nil
}

// listen delivers the server's lines to the running program, and tells it when the server is gone.
func (s *server) listen() {
	go func() {
		readMessages(s.stdout, func(m Message) { program.Send(m) })
		close(s.read)
	}()
	go func() {
		_ = s.cmd.Wait()
		s.code = 1
		if state := s.cmd.ProcessState; state != nil && state.ExitCode() >= 0 { // -1: ended by a signal
			s.code = state.ExitCode()
		}
		select { // what the server wrote last is still being read
		case <-s.read:
		case <-time.After(drainWait):
		}
		close(s.done)
		program.Send(serverExit{s.code})
	}()
}

// stop asks the server to quit, waits for it (killing it if it takes too long) and returns its exit status.
func (s *server) stop() int {
	s.conn.quit()
	s.stdin.Close()
	select {
	case <-s.done:
	case <-time.After(stopWait):
		s.killed = true
		_ = s.cmd.Process.Kill()
		<-s.done
	}
	if s.killed {
		fmt.Fprintln(os.Stderr, "minimal-go: minimal serve did not quit and was killed")
		return 1
	}
	return s.code
}

// close releases the server's files. A server that failed has its stderr shown, and its log kept.
func (s *server) close(code int) {
	s.stdout.Close()
	s.log.Close()
	if code != 0 {
		if tail := tailOf(s.logPath, tailBytes); tail != "" {
			fmt.Fprintf(os.Stderr, "%s\n", tail)
		}
		fmt.Fprintf(os.Stderr, "minimal-go: minimal serve exited with status %d (stderr log: %s)\n", code, s.logPath)
		return
	}
	if !s.keepLog {
		os.Remove(s.logPath)
	}
}

// tailOf is the last n bytes of the file, trimmed.
func tailOf(path string, n int64) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	if info, err := f.Stat(); err == nil && info.Size() > n {
		f.Seek(info.Size()-n, io.SeekStart)
	}
	data, _ := io.ReadAll(f)
	return strings.TrimSpace(string(data))
}
