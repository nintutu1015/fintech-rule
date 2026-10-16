#!/usr/bin/env python3
"""Offline Loon configuration builder and structural validator (Python 3.9+)."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.local', '.cache', 'dist', '__pycache__', '.venv'}
BUILTINS = {'DIRECT', 'REJECT', 'REJECT-DROP', 'REJECT-IMG', 'REJECT-200'}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_path(root, name):
    path = (root / name).resolve()
    relative = path.relative_to(root.resolve())
    if any(part in IGNORED for part in relative.parts):
        raise ValueError('A public source points into a private/generated directory')
    return path


def active(text):
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(('#', ';', '//'))]


def parse_sections(text):
    result = {}
    section = None
    for line in text.splitlines():
        match = re.fullmatch(r'\[([^\]]+)\]', line.strip())
        if match:
            section = match.group(1)
            if section in result:
                raise ValueError('Duplicate section: ' + section)
            result[section] = []
        elif section and active(line):
            result[section].append(line.strip())
    return result


def definitions(lines, section):
    result = {}
    for line in lines:
        if '=' not in line:
            raise ValueError('Missing assignment in ' + section)
        name, value = [part.strip() for part in line.split('=', 1)]
        if not name or name in result:
            raise ValueError('Empty or duplicate name in ' + section)
        result[name] = value
    return result


def members(value):
    return [part.strip() for part in value.split(',')[1:] if '=' not in part]


def resource_line(item):
    url = item['url']
    if not isinstance(url, str) or not url.startswith('https://') or re.search(r'[\s,]', url):
        raise ValueError('Resource URL must be a public HTTPS URL without whitespace')
    parts = [url]
    for key, value in item.items():
        if key == 'url':
            continue
        if key not in {'policy', 'tag', 'enabled'}:
            raise ValueError('Unsupported resource attribute: ' + key)
        if key == 'enabled' and not isinstance(value, bool):
            raise ValueError('enabled must be boolean')
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        if re.search(r'[\r\n,]', rendered):
            raise ValueError('Invalid resource attribute')
        parts.append(key + '=' + rendered)
    return ', '.join(parts)


def project_inputs(root=ROOT):
    project = load_json(root / 'config/project.json')
    if project.get('schema_version') != 1:
        raise ValueError('Unsupported project schema')
    sources = load_json(source_path(root, project['upstreams']))
    return project, sources


def render(root=ROOT, private=None):
    project, sources = project_inputs(root)
    if private is None:
        # Symbols only: CI checks references without possessing private nodes.
        private = {'local_proxies': ['LOCAL_NODE = SYMBOLIC_ONLY'],
                   'remote_proxies': [name + ' = SYMBOLIC_ONLY' for name in project['required_subscriptions']],
                   'mitm_private': {}}
    node_lines = private.get('local_proxies', [])
    remote_lines = private.get('remote_proxies', [])
    for lines in [node_lines, remote_lines]:
        if not isinstance(lines, list) or not lines:
            raise ValueError('Private node/subscription definitions must be nonempty lists')
        if any(not isinstance(x, str) or '\n' in x or '\r' in x for x in lines):
            raise ValueError('Private definitions must be single lines')
    names = list(definitions(node_lines, 'private nodes'))
    if any(re.search(r'[,\[\]{}]', name) for name in names):
        raise ValueError('Invalid private node name')
    subscriptions = definitions(remote_lines, 'private subscriptions')
    if not set(project['required_subscriptions']) <= subscriptions.keys():
        raise ValueError('A required subscription alias is missing')
    identity = private.get('mitm_private', {})
    if not isinstance(identity, dict) or set(identity) - {'ca-p12', 'ca-passphrase'}:
        raise ValueError('Unsupported private Mitm field')
    if any(not isinstance(value, str) or '\n' in value or '\r' in value for value in identity.values()):
        raise ValueError('Mitm private values must be single-line strings')
    rule_blocks = []
    for name in project['local_rule_files']:
        block = source_path(root, name).read_text(encoding='utf-8').strip()
        if any(line.startswith('[') for line in active(block)):
            raise ValueError('A rule fragment contains a section header')
        rule_blocks.append(block)
    values = {
        'LOCAL_PROXIES': '\n'.join(node_lines),
        'REMOTE_PROXIES': '\n'.join(remote_lines),
        'LOCAL_NODE_NAMES': ','.join(names),
        'LOCAL_RULES': '\n\n'.join(rule_blocks),
        'REMOTE_RULES': '\n'.join(resource_line(x) for x in sources['remote_rules']),
        'PLUGINS': '\n'.join(resource_line(x) for x in sources['plugins']),
        'MITM_PRIVATE': '\n'.join(key + ' = ' + value for key, value in identity.items() if value),
    }
    template = source_path(root, project['template']).read_text(encoding='utf-8')
    placeholders = set(re.findall(r'\{\{([A-Z_]+)\}\}', template))
    if placeholders != set(values):
        raise ValueError('Template placeholders do not match the supported fields')
    # A single substitution pass prevents interpreting private strings as templates.
    return re.sub(r'\{\{([A-Z_]+)\}\}', lambda match: values[match.group(1)], template)


def domain_match(line, host):
    parts = [part.strip() for part in line.split(',')]
    kind, value = parts[0].upper(), parts[1].lower()
    if kind == 'DOMAIN':
        return host == value
    if kind == 'DOMAIN-SUFFIX':
        return host == value or host.endswith('.' + value)
    if kind == 'DOMAIN-KEYWORD':
        return value in host
    return False


def validate(text, project, sources):
    sections = parse_sections(text)
    warnings = []
    definitions_by_section = {}
    for section in ['General', 'Proxy', 'Remote Proxy', 'Proxy Group', 'Remote Filter', 'Mitm']:
        definitions_by_section[section] = definitions(sections[section], section)
    groups = definitions_by_section['Proxy Group']
    known = set(BUILTINS)
    for section in ['Proxy', 'Remote Proxy', 'Proxy Group', 'Remote Filter']:
        names = set(definitions_by_section[section])
        if known & names:
            raise ValueError('A node/group/filter name collides with another name')
        known |= names
    graph = {}
    for name, value in groups.items():
        choices = members(value)
        if not choices or len(choices) != len(set(choices)):
            raise ValueError('Empty or duplicate choices in group: ' + name)
        if set(choices) - known:
            raise ValueError('Unknown member in group: ' + name)
        graph[name] = [choice for choice in choices if choice in groups]
    visited = set()

    def visit(name, stack):
        if name in stack:
            raise ValueError('Group cycle involving: ' + name)
        if name in visited:
            return
        for child in graph[name]:
            visit(child, stack | {name})
        visited.add(name)

    for name in graph:
        visit(name, set())
    legacy = {item['line']: item for item in project['legacy_policy_omissions']}
    rules = sections['Rule']
    if not set(legacy) <= set(rules):
        raise ValueError('A legacy exception was removed; update its finding record explicitly')
    seen = {}
    supported = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'IP-CIDR', 'IP-CIDR6', 'GEOIP', 'FINAL'}
    for index, line in enumerate(rules, 1):
        parts = [part.strip() for part in line.split(',')]
        if len(parts) < 2 or parts[0].upper() not in supported:
            raise ValueError('Unsupported/invalid local rule at position ' + str(index))
        kind = parts[0].upper()
        if kind in ['IP-CIDR', 'IP-CIDR6']:
            network = ipaddress.ip_network(parts[1], strict=True)
            if network.version != (6 if kind == 'IP-CIDR6' else 4):
                raise ValueError('CIDR address family does not match rule type')
        if line in legacy:
            warnings.append(legacy[line]['id'] + ': preserved missing policy')
            continue
        policy_index = 1 if kind == 'FINAL' else 2
        if len(parts) <= policy_index or parts[policy_index] not in known:
            raise ValueError('Unknown or missing policy at local rule position ' + str(index))
        condition = tuple(parts[:policy_index])
        if condition in seen and seen[condition] != parts[policy_index]:
            raise ValueError('Conflicting policies for the same local match condition')
        if condition in seen:
            warnings.append('Duplicate local match condition at position ' + str(index))
        seen[condition] = parts[policy_index]
    finals = [line for line in rules if line.upper().startswith('FINAL,')]
    if len(finals) != 1 or finals[0] != rules[-1]:
        raise ValueError('Exactly one FINAL is required at the end of local rules')
    urls, tags = set(), set()
    for item in sources['remote_rules']:
        resource_line(item)
        if item['policy'] not in known:
            raise ValueError('Unknown policy in remote rule: ' + item.get('tag', 'untagged'))
        if item['url'] in urls or item['tag'] in tags:
            raise ValueError('Duplicate remote rule URL or tag')
        urls.add(item['url']); tags.add(item['tag'])
    for item in sources['plugins']:
        resource_line(item)
        if item.get('policy') is not None and item['policy'] not in known:
            raise ValueError('Unknown plugin policy')
    return sections, warnings


def check_expectations(sections, sources, expectations):
    groups = definitions(sections['Proxy Group'], 'Proxy Group')
    rules = sections['Rule']
    for host, expected in expectations['local_domains'].items():
        matches = [line for line in rules if domain_match(line, host)]
        actual = matches[0].split(',')[2].strip() if matches else None
        if actual != expected:
            raise ValueError('Local routing regression for ' + host)
    covered = {host.lower() for host in expectations['local_domains']}
    for line in rules:
        parts = [part.strip() for part in line.split(',')]
        if parts[0].upper() in {'DOMAIN', 'DOMAIN-SUFFIX'} and parts[1].lower() not in covered:
            raise ValueError('Local rule without a routing expectation: ' + parts[1])
    if rules[-1] != 'FINAL,' + expectations['final']:
        raise ValueError('FINAL regression')
    for name, expected in expectations['group_members_exact'].items():
        if members(groups[name]) != expected:
            raise ValueError('Group menu regression: ' + name)
    for name, expected in expectations['group_members_contain'].items():
        if not set(expected) <= set(members(groups[name])):
            raise ValueError('Group menu regression: ' + name)
    if set(expectations['absent_groups']) & set(groups):
        raise ValueError('A removed group was reintroduced')
    indexed = {item['tag']: item for item in sources['remote_rules']}
    tags = list(indexed)
    for tag, policy in expectations['remote_policy'].items():
        if indexed[tag]['policy'] != policy:
            raise ValueError('Remote routing regression: ' + tag)
    for before, after in expectations['remote_before']:
        if tags.index(before) >= tags.index(after):
            raise ValueError('Remote priority regression: ' + before)


def scan_public(root=ROOT):
    patterns = [
        re.compile(r'[?&](?:token|access_token|api_key|secret)=([^\s,\"<>]+)', re.I),
        re.compile(r'^\s*(?:ca-p12|ca-passphrase)\s*=\s*\S+', re.M | re.I),
        re.compile(r'^\s*[^#\n=]+\s*=\s*(?:vmess|trojan|vless|shadowsocks|hysteria2|anytls)\s*,', re.M | re.I),
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    ]
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True).stdout.decode().split('\0')
    for name in filter(None, tracked):
        if any(part in IGNORED for part in Path(name).parts):
            raise ValueError('A private/generated path is tracked: ' + name)
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('Public symlink requires manual review: ' + str(relative))
        if not path.is_file():
            continue
        if path.suffix.lower() in {'.p12', '.pfx', '.pem', '.key'} or path.name.startswith('.env'):
            raise ValueError('Private file in public source tree: ' + str(relative))
        text = path.read_text(encoding='utf-8')
        if any(pattern.search(text) for pattern in patterns):
            raise ValueError('Potential credential in public file: ' + str(relative))


def check(root=ROOT):
    scan_public(root)
    project, sources = project_inputs(root)
    sections, warnings = validate(render(root), project, sources)
    check_expectations(sections, sources, load_json(root / 'tests/expectations.json'))
    return warnings


def build(root=ROOT, private_path=None, output=None):
    check(root)
    private_path = private_path or root / '.local/private.json'
    private = load_json(private_path)
    if private.get('schema_version') != 1 or 'REPLACE_WITH_' in json.dumps(private):
        raise ValueError('Private settings are missing or still contain example placeholders')
    text = render(root, private)
    project, sources = project_inputs(root)
    validate(text, project, sources)
    output = (output or root / 'dist/loon.lcf').resolve()
    output.relative_to((root / 'dist').resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.loon-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as f:
            f.write(text)
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def compare_baseline(root=ROOT):
    output = build(root)
    before = parse_sections((root / '.local/baseline.lcf').read_text())
    after = parse_sections(output.read_text())
    if set(before) != set(after):
        raise ValueError('Baseline section set changed')
    for section in before:
        normalize = (lambda line: ','.join(part.strip() for part in line.split(','))) if section in ['Remote Rule', 'Plugin'] else (lambda line: line)
        if list(map(normalize, before[section])) != list(map(normalize, after[section])):
            raise ValueError('Baseline differs in section: ' + section)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'scan', 'build', 'verify-baseline'])
    args = parser.parse_args()
    try:
        if args.command == 'check':
            warnings = check()
            print('Structure and regression checks passed (not a native Loon import).')
            for warning in warnings:
                print('WARN:', warning)
        elif args.command == 'scan':
            scan_public(); print('Public-source credential scan passed; heuristic coverage only.')
        elif args.command == 'build':
            print('Private output:', build())
        else:
            compare_baseline(); print('Generated active configuration matches the frozen local baseline.')
    except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
        # JSON errors can contain secret values; never echo private input payloads.
        if isinstance(error, json.JSONDecodeError):
            message = 'Invalid JSON; check input syntax locally.'
        elif isinstance(error, (KeyError, TypeError, IndexError)):
            message = 'Input schema is incomplete or invalid.'
        elif isinstance(error, FileNotFoundError):
            message = 'Required file missing; see README for local initialization.'
        else:
            message = str(error)
        raise SystemExit('ERROR: ' + message)


if __name__ == '__main__':
    main()
