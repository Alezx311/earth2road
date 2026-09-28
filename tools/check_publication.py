#!/usr/bin/env python3
"""Audit Git publication candidates without printing matched secrets.

A conservative local hygiene check; also use a maintained dependency advisory service.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {'.venv', '.tools', '.cache', '.git', '.godot', '__pycache__',
                'data', 'dist', 'build', 'logs', 'notes', 'graphify-out',
                '.codex', '.claude', '.opencode', '.agents'}
BLOCKED_SUFFIXES = {'.exe', '.dll', '.zip', '.pbf', '.pyc', '.pem', '.key'}
SECRET_PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'Slack token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'AWS access key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'API key': re.compile(r'\b(?:sk-proj-|sk-ant-api03-)[A-Za-z0-9_-]{30,}\b'),
    'Google API key': re.compile(r'\bAIza[A-Za-z0-9_-]{35}\b'),
}
PRIVATE_PATH = re.compile(r'(?:[A-Z]:[/\\](?:Users|js)[/\\]|/home/[a-zA-Z0-9_-]+/)', re.I)


def inspect_file(root, relative):
    path = root / relative
    findings = []
    parts = relative.parts
    if any(part in BLOCKED_DIRS or part.endswith('.egg-info') for part in parts):
        findings.append('local/generated directory')
    if path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example':
        findings.append('environment secrets file')
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        findings.append('binary/archive/credential file')
    if parts[:2] == ('game', 'assets') and path.name != '.gdignore':
        findings.append('downloaded asset')
    if path.is_symlink():
        return findings + ['symbolic link']
    if not path.is_file():
        return findings + ['missing candidate file']
    if path.stat().st_size > 5_000_000:
        findings.append('source file exceeds 5 MB')
    try:
        text = path.read_text(encoding='utf8')
    except UnicodeDecodeError:
        if path.suffix.lower() not in {'.png', '.jpg'}:
            findings.append('unexpected binary or non-UTF8 file')
        return findings
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(label)
    if PRIVATE_PATH.search(text):
        findings.append('machine-specific user/workspace path')
    if path.suffix == '.md':
        for link in re.findall(r'\]\(([^)]+)\)', text):
            target = link.split('#', 1)[0].strip('<>')
            if not target or re.match(r'[a-z]+:', target):
                continue
            if not (path.parent / unquote(target)).exists():
                findings.append('broken Markdown link: ' + target)
    return findings


def audit(root):
    raw = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root)
    files = sorted({Path(p) for p in raw.decode('utf8').split('\0') if p})
    if not files:
        raise RuntimeError('No Git publication candidates found')
    findings = {p.as_posix(): issues for p in files if (issues := inspect_file(root, p))}
    return {'files': len(files), 'bytes': sum((root/p).stat().st_size for p in files if (root/p).is_file()),
            'findings': findings, 'ok': not findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
