package main

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

var (
	command     = flag.String("c", "", "command")
	module      = flag.String("m", "", "module name")
	logfile     = flag.String("l", "", "log file path")
	python      = flag.String("p", "", "python path")
	env         = flag.String("e", "", "env")
	maxFileSize = 10 * 1024 * 1024
)

func main() {
	flag.Parse()

	if *command == "" && (*python == "" || *module == "") {
		fmt.Println("python interpreter or module name is not set")
		os.Exit(1)
	}

	if *logfile == "" {
		fmt.Println("log file path is not set")
		os.Exit(1)
	}

	envs := os.Environ()
	if *env != "" {
		envs = append(envs, *env)
	}

	var cmd *exec.Cmd
	if *command != "" {
		cmd = exec.Command("/bin/sh", "-c", *command)
	} else {
		cmd = exec.Command(*python, "-m", *module)
	}
	cmd.Env = envs

	stdout, _ := cmd.StdoutPipe()
	cmd.Start()

	logf, _ := os.OpenFile(*logfile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	defer logf.Close()

	reader := bufio.NewReader(stdout)
	var buffer bytes.Buffer
	for {
		line, _, err := reader.ReadLine()
		if err != nil || io.EOF == err {
			break
		}
		buffer.Write(line)
		logf.Write(buffer.Bytes())
		fmt.Print(buffer.String())
		buffer.Reset()

		fileInfo, _ := logf.Stat()
		if fileInfo.Size() > int64(maxFileSize) {
			logf.Close()
			os.Rename(*logfile, fmt.Sprintf("%s_%s.log", strings.TrimSuffix(*logfile, ".log"), time.Now().Format("20060102150405")))
			logf, _ = os.OpenFile(*logfile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		}
	}

	cmd.Wait()
}
