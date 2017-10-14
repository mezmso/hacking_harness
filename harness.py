#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import tty
import termios
import readline
import select
import pty
import sys
from subprocess import Popen
import base64
import time
import glob


'''
Basic Harness class,
runs process and sets up environment
provides:
    interact -- interact with process
    setty -- set tty to raw
    unsetty -- set tty to whatever it was before
    write_master -- write to master fileno
    read_master -- read from master fileno, can't seem to get this to behave
'''
class HackingHarness:
    def __init__(self, cmd):
        self.old_tty = termios.tcgetattr(sys.stdin)
        self.master_fd, self.slave_fd = pty.openpty()
        self.proc = Popen(cmd,
                  preexec_fn=os.setsid,
                  stdin=self.slave_fd,
                  stdout=self.slave_fd,
                  stderr=self.slave_fd,
                  universal_newlines=True)
    def interact(self, keymap):
        self.setty()
        while self.proc.poll() is None:
            r, w, e = select.select([sys.stdin, self.master_fd], [], [])
            if sys.stdin in r:
                d = os.read(sys.stdin.fileno(), 10240)
                if len(d) == 1:
                    for k in keymap:
                        if ord(d) == k[0]:
                            try:
                                k[1]()
                                self.setty()
                                continue
                            except Exception as e:
                                print(e)
                                pass
                            finally:
                                self.setty()
                os.write(self.master_fd, d)
            elif self.master_fd in r:
                o = os.read(self.master_fd, 10240)
                if o:
                    os.write(sys.stdout.fileno(), o)
        self.unsetty()

    def setty(self):
        tty.setraw(sys.stdin.fileno())
        self.new_tty = termios.tcgetattr(sys.stdin)
    def unsetty(self):
        termios.tcsetattr(sys.stdin, termios.TCSANOW, self.old_tty)

    def write_master(self, content):
        os.write(self.master_fd, content)
    def write_slave(self, content):
        os.write(self.slave_fd, content)
    def read_master(self, size):
        os.read(self.master_fd, size)
    def read_slave(self, size):
        os.read(self.slave_fd, size)

'''
Utilities for the harness
'''
class HackingHarnessShell:
    def __init__(self, harness):
        self.harness_session = harness
    def complete(self, text,state):
        COMMANDS = ['get', 'put', 'runraw','runpy', 'exit']
        volcab = []
        for c in COMMANDS:
            volcab.append(c)
        for g in glob.glob(text+"*"):
            volcab.append(g)

        results = [x for x in volcab if x.startswith(text)] + [None]
        return results[state]

    def shell(self):
        self.harness_session.unsetty()

        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(' \t\n;')
        readline.set_completer(self.complete)

        while True:
            data = input('harness> ')

            command = data.split(' ')

            try:
                if command[0] == 'put':
                    self.put(command[1], command[2])
                elif command[0] == 'get':
                    self.get(command[1], command[2])
                elif command[0] == 'runraw':
                    self.runraw(command[1])
                elif command[0] == 'runpy':
                    self.runpy(command[1])
                elif command[0] == 'exit':
                    return

            except IndexError as e:
                print(e)
                print("[-] missing argument")
        self.harness_session.setty()

    # put a file on a remote system via shell
    def put(self, src, dst):
        with open(src, 'rb') as f:
            data = base64.b64encode(f.read())
            self.harness_session.write_master('echo "{}" | base64 -d > {}\n'.format(data.decode(), dst).encode())
            print("[+] sent {} bytes to {}\n".format(len(data), dst))

    # get a file from a remote system via shell
    def get(self, src, dst):
        print('[*] calculating file size of {}'.format(src))
        self.harness_session.write_master('cat {} | base64 -w 0 | wc -c\n'.format(src).encode())
        print('[*] waiting for 1 second for the command output')
        time.sleep(1)
        size = os.read(self.harness_session.master_fd, 10240)
        size = size.decode().split('\r\n')[1].split('\t')[0]
        print('[+] {} is {} bytes (b64)\nGetting now'.format(src, size))

        sleep_time = input('how long should I sleep for when getting the output of the file? ')
        self.harness_session.write_master('cat {} | base64 -w 0; echo\r\n'.format(src).encode())
        time.sleep(int(sleep_time))
        try:
            data = os.read(self.harness_session.master_fd, int(size)+128)
        except ValueError:
            print('[-] something went wrong when getting file/size')
            print('[-] size: {}'.format(size))
            return
        data = data.decode().split('\r\n')[2]
        try:
            data = base64.b64decode(data)
        except:
            print('error decoding data')
        with open(dst, 'wb') as f:
            f.write(data)

    # run directly in the context of the shell
    def runraw(self, src):
        with open(src, 'r') as f:
            data = f.read()
        self.harness_session.write_master(data.encode())
        time.sleep(0.05)

    # launch python and then execute input
    def runpy(self, src, exit_when_done=True):
        with open(src, 'r') as f:
            data = f.read()
        self.harness_session.write_master('python\n'.encode())
        time.sleep(1)
        self.harness_session.write_master(data.encode())
        if exit_when_done:
            self.harness_session.write_master('exit()\n'.encode())

'''
example of a custom harness provider
'''
class CustomHackingHarness:
    DIRECTORY = os.path.dirname(os.path.realpath(__file__))
    def __init__(self, harness_shell):
        self.h_shell = harness_shell
    def unset_histfile(self):
        self.h_shell.runraw(DIRECTORY+'/scripts/uh.sh')


if __name__ == '__main__':
    h = HackingHarness(sys.argv[1:])
    hs = HackingHarnessShell(h)
    c = CustomHackingHarness(hs)
    keys = [
        (29, hs.shell), # C+]
        (27, c.unset_histfile) # C+[
    ]
    try:
        h.interact(keys)
    except Exception as e:
        h.unsetty()
        raise
    h.unsetty()
