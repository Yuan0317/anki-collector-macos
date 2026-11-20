#!/usr/bin/env python3
"""Build a macOS launcher; reuse dependencies and never change collector code."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


def apple_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='~/anki-collector')
    parser.add_argument('--python', help='Existing Python executable; default PROJECT/.venv/bin/python')
    parser.add_argument('--script', default='anki_collector.py', help='Script relative to project, or absolute')
    parser.add_argument('--output', required=True, help='New .app path; will not replace existing files')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This builder supports macOS only.')
    project = Path(args.project).expanduser().resolve()
    # Do not resolve the executable symlink: that would bypass virtualenv discovery.
    python = Path(os.path.abspath(os.path.expanduser(args.python))) if args.python else project / '.venv/bin/python'
    script = Path(args.script).expanduser()
    if not script.is_absolute():
        script = project / script
    output = Path(args.output).expanduser().absolute()
    if not project.is_dir():
        parser.error('Project directory does not exist: ' + str(project))
    if not python.is_file() or not os.access(python, os.X_OK):
        parser.error('Python executable is missing or not executable: ' + str(python))
    if not script.is_file():
        parser.error('Collector script does not exist: ' + str(script))
    if output.suffix != '.app':
        parser.error('--output must end in .app')
    if output.exists():
        parser.error('Output already exists; choose another path: ' + str(output))
    if not Path('/usr/bin/osacompile').exists():
        parser.error('macOS osacompile is unavailable.')
    shell = '''set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export ARGOS_CHUNK_TYPE=SPACY
export ARGOS_DEVICE_TYPE=cpu
export PYTHONUNBUFFERED=1
LOG_DIR="$HOME/Library/Logs/AnkiCollector"
mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/launcher.log" 2>&1
printf '\\n--- Launch: '
/bin/date
'''
    shell += 'cd ' + shlex.quote(str(project)) + '\n'
    shell += 'exec ' + shlex.quote(str(python)) + ' ' + shlex.quote(str(script)) + '\n'
    message = '收集器启动或运行失败。请查看 ~/Library/Logs/AnkiCollector/launcher.log。错误：'
    source = ('on run\ntry\n«event sysoexec» ' + apple_string(shell) +
              '\non error errText number errNum\n«event sysodlog» (' +
              apple_string(message) + ' & errText)\nend try\nend run\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Compile outside the destination so failure does not leave a half-built app.
    with tempfile.TemporaryDirectory(prefix='anki-app-', dir=str(output.parent)) as temp:
        built = Path(temp) / output.name
        subprocess.run(['/usr/bin/osacompile', '-o', str(built), '-e', source], check=True)
        if output.exists():
            parser.error('Output was created by another process; refusing to replace it.')
        built.rename(output)
    print('Created:', output)
    print('Uses existing Python:', python)
    print('No dependencies installed; collector not launched.')


if __name__ == '__main__':
    main()
