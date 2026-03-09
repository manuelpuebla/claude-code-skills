#!/usr/bin/env python3
"""
autopsy.py - Project autopsy data gatherer

Scans a project directory and produces a structured report:
1. DAG structure from ARCHITECTURE.md (nodes, deps, status, phases)
2. README sections + claim indicators for semantic analysis
3. BENCHMARKS.md presence and structure
4. Lean code inventory (defs, theorems, sorry, axioms, #eval, @[simp])
5. Aggregate metrics and coverage gaps

Usage:
    python3 autopsy.py /path/to/project
    python3 autopsy.py /path/to/project --json
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

# ─── Spec Audit Integration ──────────────────────────────────────
SPEC_AUDIT_SCRIPT = Path(__file__).parent.parent.parent / "plan-project" / "scripts" / "spec_audit.py"


# ─── ARCHITECTURE.md Parser ──────────────────────────────────────

def parse_architecture(path):
    """Parse ARCHITECTURE.md for DAG tables, phases, blocks, components, versions."""
    result = {
        'found': False,
        'phases': [],
        'dag_nodes': [],
        'blocks': [],
        'components': [],
        'versions': [],
    }

    if not path.exists():
        return result

    result['found'] = True
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')

    # Extract phases
    phase_re = re.compile(
        r'###?\s+Fase\s+(\d+)(?:\s+Subfase\s+(\d+))?'
        r'\s*[:\-–]?\s*(.*)',
        re.IGNORECASE,
    )
    for line in lines:
        m = phase_re.match(line.strip())
        if m:
            result['phases'].append({
                'fase': int(m.group(1)),
                'subfase': int(m.group(2)) if m.group(2) else None,
                'name': m.group(3).strip().rstrip('(').strip(),
            })

    # Extract DAG nodes from tables
    # Format: | N1 Name | FUND | deps | status |
    dag_re = re.compile(
        r'\|\s*(.+?)\s*\|'
        r'\s*(FUND|CRIT|HOJA|PARALELO|FUNDACIONAL|CR[IÍ]TICO)\s*\|'
        r'\s*(.*?)\s*\|'
        r'\s*(.*?)\s*\|',
        re.IGNORECASE,
    )
    for line in lines:
        m = dag_re.search(line)
        if m:
            node_name = m.group(1).strip()
            node_type = m.group(2).strip().upper()
            deps_raw = m.group(3).strip()
            status_raw = m.group(4).strip()

            # Normalize type
            type_map = {'FUNDACIONAL': 'FUND', 'CRÍTICO': 'CRIT', 'CRITICO': 'CRIT'}
            node_type = type_map.get(node_type, node_type)

            # Parse deps
            dep_list = []
            if deps_raw and deps_raw not in ('—', '-', '–', 'none', ''):
                dep_list = [d.strip() for d in re.split(r'[,;]', deps_raw) if d.strip()]

            completed = '✓' in status_raw or 'completed' in status_raw.lower()

            result['dag_nodes'].append({
                'name': node_name,
                'type': node_type,
                'deps': dep_list,
                'status': 'completed' if completed else 'pending',
            })

    # Extract blocks
    block_re = re.compile(
        r'-\s*\[(x| )\]\s*\*\*(?:Block|Bloque)\s*(\d+).*?\*\*\s*[:\-–]?\s*(.*)',
        re.IGNORECASE,
    )
    for line in lines:
        m = block_re.search(line)
        if m:
            result['blocks'].append({
                'completed': m.group(1).strip().lower() == 'x',
                'number': int(m.group(2)),
                'content': m.group(3).strip(),
            })

    # Extract component tables
    # Format: | Component | Files | LOC | Theorems | Role |
    # or:     | Component | Files | LOC | Role |
    comp_re = re.compile(
        r'\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*([\d,~.]+)\s*\|\s*(.*?)\s*\|'
    )
    in_comp_section = False
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if any(k in stripped for k in ('component', 'module', 'módulo')) and '|' in line and '---' not in line:
            # This is likely a table header
            in_comp_section = True
            continue
        if in_comp_section and line.strip().startswith('|---'):
            continue  # skip separator
        if in_comp_section and not line.strip().startswith('|'):
            in_comp_section = False
            continue
        if in_comp_section:
            m = comp_re.search(line)
            if m:
                name = m.group(1).strip()
                if name.startswith('---') or name.lower() in ('component', 'module', 'módulo'):
                    continue
                result['components'].append({
                    'name': name,
                    'files': m.group(2).strip(),
                    'loc': m.group(3).strip(),
                    'extra': m.group(4).strip(),
                })

    # Extract version history
    ver_re = re.compile(
        r'\|\s*\*?\*?v?([\d.]+)\*?\*?\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|'
    )
    for line in lines:
        m = ver_re.search(line)
        if m:
            ver = m.group(1).strip()
            if re.match(r'\d+\.\d+', ver):
                result['versions'].append({
                    'version': ver,
                    'date': m.group(2).strip(),
                    'highlights': m.group(3).strip(),
                })

    return result


# ─── dag.json Parser ─────────────────────────────────────────────

def parse_dag_json(path):
    """Parse dag.json for machine-readable DAG data (preferred over ARCHITECTURE.md regex)."""
    result = {
        'found': False,
        'version': '',
        'phases': [],
        'dag_nodes': [],
        'blocks': [],
    }

    if not path.exists():
        return result

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, IOError):
        return result

    result['found'] = True
    result['version'] = data.get('version', '')

    for phase in data.get('phases', []):
        result['phases'].append({
            'id': phase.get('id', ''),
            'name': phase.get('name', ''),
            'status': phase.get('status', 'pending'),
        })

        for node in phase.get('nodes', []):
            # Normalize type
            raw_type = node.get('type', 'HOJA').upper()
            type_map = {'FUNDACIONAL': 'FUND', 'CRÍTICO': 'CRIT', 'CRITICO': 'CRIT'}
            ntype = type_map.get(raw_type, raw_type)

            result['dag_nodes'].append({
                'name': f"{node.get('id', '')} {node.get('name', '')}".strip(),
                'id': node.get('id', ''),
                'type': ntype,
                'deps': node.get('deps', []),
                'status': node.get('status', 'pending'),
                'files': node.get('files', []),
                'metrics': node.get('metrics', {}),
                'properties': node.get('properties', {}),
                'blocks_ids': node.get('blocks', []),
            })

        for block in phase.get('blocks', []):
            result['blocks'].append({
                'id': block.get('id', ''),
                'name': block.get('name', ''),
                'nodes': block.get('nodes', []),
                'completed': block.get('status', '') == 'completed',
                'number': int(re.search(r'\d+', block.get('id', '0')).group())
                    if re.search(r'\d+', block.get('id', '0')) else 0,
                'content': ', '.join(block.get('nodes', [])),
                'closed_at': block.get('closed_at'),
            })

    return result


# ─── README.md Parser ─────────────────────────────────────────────

def parse_readme(path):
    """Extract sections and claim indicators from README.md."""
    result = {
        'found': False,
        'title': '',
        'subtitle': '',
        'sections': [],
        'claims': [],
    }

    if not path.exists():
        return result

    result['found'] = True
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')

    # Extract title and subtitle
    for i, line in enumerate(lines):
        if line.startswith('# ') and not result['title']:
            result['title'] = line[2:].strip()
        elif result['title'] and not line.startswith('#') and line.strip() and not result['subtitle']:
            result['subtitle'] = line.strip().strip('*')
            break

    # Extract sections with headers
    current_header = None
    current_lines = []
    for line in lines:
        if re.match(r'^#{1,3}\s+', line):
            if current_header:
                result['sections'].append({
                    'header': current_header,
                    'content': '\n'.join(current_lines).strip()[:500],
                })
            current_header = re.sub(r'^#+\s+', '', line).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_header:
        result['sections'].append({
            'header': current_header,
            'content': '\n'.join(current_lines).strip()[:500],
        })

    # Detect claim indicators
    claim_patterns = [
        # Correctness/soundness claims
        (r'(?i)\b(?:zero\s+sorry|no\s+sorry)', 'ZERO_SORRY'),
        (r'(?i)\b(?:zero\s+axiom|no\s+axiom)', 'ZERO_AXIOM'),
        (r'(?i)\b(?:fully\s+)?verif(?:ied|ication|icado)', 'VERIFIED'),
        (r'(?i)\bsound(?:ness)?\b', 'SOUNDNESS'),
        (r'(?i)\bcorrect(?:ness)?\b', 'CORRECTNESS'),
        (r'(?i)\b(?:machine[- ]check(?:ed)?|formally\s+proven)', 'MACHINE_CHECKED'),
        # Preservation/invariance
        (r'(?i)\bpreserv(?:es?|ing|ation)\b', 'PRESERVATION'),
        (r'(?i)\binvariant\b', 'INVARIANT'),
        (r'(?i)\bequivalen(?:t|ce)\b', 'EQUIVALENCE'),
        (r'(?i)\bbijection|isomorphi', 'BIJECTION'),
        # Generation/production
        (r'(?i)\bgener(?:ates?|ation)\b', 'GENERATION'),
        (r'(?i)\bproduc(?:es?|tion)\b', 'PRODUCTION'),
        (r'(?i)\bcompil(?:es?|ation|er)\b', 'COMPILATION'),
        # Optimization
        (r'(?i)\boptimiz(?:es?|ation|er)\b', 'OPTIMIZATION'),
        (r'(?i)\breduc(?:es?|tion)\b', 'REDUCTION'),
        (r'(?i)\belimin(?:ates?|ation)\b', 'ELIMINATION'),
        # Support/acceptance
        (r'(?i)\bsupports?\b', 'SUPPORT'),
        (r'(?i)\bhandles?\b', 'HANDLES'),
        # Completeness
        (r'(?i)\bcomplete(?:ness)?\b', 'COMPLETENESS'),
        (r'(?i)\bdecidab(?:le|ility)\b', 'DECIDABILITY'),
        # TCB
        (r'(?i)\btcb\b|trusted\s+comput', 'TCB'),
    ]

    for i, line in enumerate(lines):
        for pattern, claim_type in claim_patterns:
            if re.search(pattern, line):
                result['claims'].append({
                    'type': claim_type,
                    'line': i + 1,
                    'text': line.strip()[:200],
                })
                break  # one claim per line

    # Deduplicate by text
    seen = set()
    unique_claims = []
    for c in result['claims']:
        if c['text'] not in seen:
            seen.add(c['text'])
            unique_claims.append(c)
    result['claims'] = unique_claims

    return result


# ─── BENCHMARKS.md Parser ─────────────────────────────────────────

def parse_benchmarks(path):
    """Check for BENCHMARKS.md presence and extract structure."""
    result = {'found': False, 'sections': [], 'has_criteria': False, 'has_results': False}

    if not path.exists():
        return result

    result['found'] = True
    text = path.read_text(encoding='utf-8')

    for line in text.split('\n'):
        if re.match(r'^#{1,3}\s+', line):
            header = re.sub(r'^#+\s+', '', line).strip()
            result['sections'].append(header)

    text_lower = text.lower()
    result['has_criteria'] = any(k in text_lower for k in ('criterio', 'criteria', 'rubric', 'rúbrica'))
    result['has_results'] = any(k in text_lower for k in ('resultado', 'result', 'pass', 'fail'))

    return result


# ─── Lean Source Scanner ──────────────────────────────────────────

def _normalize_name(name):
    """Convert camelCase to snake_case for fuzzy matching.

    Examples: addNode → add_node, BestNodeInv → best_node_inv
    """
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    return s.lower()


def scan_lean_files(project_dir):
    """Scan all .lean files for definitions, theorems, sorry, etc."""
    result = {
        'files': [],
        'totals': {
            'files': 0, 'loc': 0,
            'defs': 0, 'theorems': 0, 'lemmas': 0,
            'instances': 0, 'structures': 0, 'inductives': 0, 'classes': 0,
            'sorry': 0, 'axioms': 0,
            'evals': 0, 'simp_attrs': 0,
            'slim_check': 0,
        },
        'sorry_locations': [],
        'axiom_locations': [],
        'eval_locations': [],
        'uncovered_defs': [],
        'outside_tcb_defs': [],
    }

    lean_files = sorted(project_dir.rglob('*.lean'))
    # Exclude .lake directory, lakefile
    lean_files = [
        f for f in lean_files
        if '.lake' not in str(f)
        and 'lake-packages' not in str(f)
        and f.name.lower() != 'lakefile.lean'
    ]

    if not lean_files:
        return result

    all_theorem_names = set()
    all_def_names = {}  # name → file
    all_type_def_names = set()  # structures, classes, inductives
    theorem_context_ids = set()  # all identifiers referenced in theorem blocks
    io_files = set()  # files with IO return types (outside TCB)

    for lf in lean_files:
        try:
            text = lf.read_text(encoding='utf-8')
        except Exception:
            continue

        lines = text.split('\n')
        loc = len([l for l in lines if l.strip() and not l.strip().startswith('--')])

        rel_path = str(lf.relative_to(project_dir))

        # Strip block comments and strings for declaration detection
        code_text = re.sub(r'/[-–][\s\S]*?[-–]/', '', text)  # block comments
        code_text = re.sub(r'"[^"]*"', '""', code_text)  # string literals
        code_text = re.sub(r'--[^\n]*', '', code_text)  # line comments

        # Pattern counts (on comment-free text)
        defs = re.findall(r'\bdef\s+(\w+)', code_text)
        theorems = re.findall(r'\btheorem\s+(\w+)', code_text)
        lemmas = re.findall(r'\blemma\s+(\w+)', code_text)
        instances = len(re.findall(r'\binstance\s+', code_text))
        structures = re.findall(r'\bstructure\s+(\w+)', code_text)
        inductives = re.findall(r'\binductive\s+(\w+)', code_text)
        classes = re.findall(r'\bclass\s+(\w+)', code_text)
        axioms = re.findall(r'\baxiom\s+(\w+)', code_text)
        evals = [(i + 1, l.strip()) for i, l in enumerate(lines) if re.search(r'#eval\b', l)]
        simp_attrs = len(re.findall(r'@\[(?:[^\]]*,\s*)?simp(?:\s*,[^\]]*)?\]', code_text))
        # sorry detection: exclude sorry inside strings, comments, or block comments
        # First, strip block comments (/- ... -/) to track which lines are inside them
        in_block_comment = 0
        code_lines = []  # (line_no, text, is_code)
        for i, l in enumerate(lines):
            stripped = l.strip()
            # Count block comment opens/closes on this line
            opens = len(re.findall(r'/[-–]', l))
            closes = len(re.findall(r'[-–]/', l))
            was_in_comment = in_block_comment > 0
            in_block_comment += opens - closes
            in_block_comment = max(0, in_block_comment)
            is_in_comment = was_in_comment or in_block_comment > 0
            code_lines.append((i + 1, stripped, not is_in_comment))

        sorrys = []
        for line_no, stripped, is_code in code_lines:
            if not is_code or not stripped or stripped.startswith('--'):
                continue
            if re.search(r'\bsorry\b', stripped):
                # Remove string contents and inline comments
                no_strings = re.sub(r'"[^"]*"', '""', stripped)
                no_strings = re.sub(r'--.*$', '', no_strings)
                if re.search(r'\bsorry\b', no_strings):
                    sorrys.append((line_no, stripped))
        slim_checks = len(re.findall(r'\bslim_check\b', code_text))

        file_info = {
            'path': rel_path,
            'loc': loc,
            'defs': len(defs),
            'theorems': len(theorems),
            'lemmas': len(lemmas),
            'instances': instances,
            'structures': len(structures),
            'inductives': len(inductives),
            'classes': len(classes),
            'sorry': len(sorrys),
            'axioms': len(axioms),
            'evals': len(evals),
            'simp_attrs': simp_attrs,
            'slim_check': slim_checks,
        }
        result['files'].append(file_info)

        # Track names for coverage analysis
        for d in defs:
            all_def_names[d] = rel_path
        all_theorem_names.update(theorems)
        all_theorem_names.update(lemmas)
        all_type_def_names.update(structures)
        all_type_def_names.update(inductives)
        all_type_def_names.update(classes)

        # Detect IO-heavy files (outside TCB)
        if re.search(r'\bIO\b', code_text) and (len(theorems) + len(lemmas)) == 0:
            io_files.add(rel_path)

        # Collect identifiers referenced in theorem/lemma contexts (cross-file coverage)
        n_proofs = len(theorems) + len(lemmas)
        if n_proofs >= 5:
            # Spec-heavy file: scan ALL identifiers — the whole file is specification.
            # Catches sub-predicates in composite defs (e.g., HashconsConsistent in EGraphWF).
            for word in re.findall(r'\b[a-zA-Z_]\w*\b', code_text):
                theorem_context_ids.add(word)
        elif n_proofs > 0:
            # Few theorems: scan only theorem blocks to avoid noise from impl defs
            in_theorem = False
            for tline in code_text.split('\n'):
                if re.match(
                    r'\s*(private\s+|protected\s+)?(?:theorem|lemma)\s+', tline
                ):
                    in_theorem = True
                elif in_theorem and re.match(
                    r'\s*(private\s+|protected\s+)?'
                    r'(?:theorem|def|lemma|structure|inductive|class|'
                    r'instance|section|namespace|end)\s',
                    tline,
                ):
                    in_theorem = False
                if in_theorem:
                    for word in re.findall(r'\b[a-zA-Z_]\w*\b', tline):
                        theorem_context_ids.add(word)

        # Track locations
        for line_no, line_text in sorrys:
            result['sorry_locations'].append({'file': rel_path, 'line': line_no, 'text': line_text})
        for ax in axioms:
            result['axiom_locations'].append({'file': rel_path, 'name': ax})
        for line_no, line_text in evals:
            result['eval_locations'].append({'file': rel_path, 'line': line_no, 'text': line_text})

        # Update totals
        result['totals']['files'] += 1
        result['totals']['loc'] += loc
        result['totals']['defs'] += len(defs)
        result['totals']['theorems'] += len(theorems)
        result['totals']['lemmas'] += len(lemmas)
        result['totals']['instances'] += instances
        result['totals']['structures'] += len(structures)
        result['totals']['inductives'] += len(inductives)
        result['totals']['classes'] += len(classes)
        result['totals']['sorry'] += len(sorrys)
        result['totals']['axioms'] += len(axioms)
        result['totals']['evals'] += len(evals)
        result['totals']['simp_attrs'] += simp_attrs
        result['totals']['slim_check'] += slim_checks

    # Find uncovered defs using multi-signal heuristic
    skip_names = {
        'main', 'toString', 'repr', 'beq', 'hash', 'compare',
        'decEq', 'instBEq', 'instHashable', 'instRepr', 'instToString',
        'mk', 'default', 'empty', 'init',
    }

    # Pre-compute normalized theorem names for camelCase↔snake_case matching
    normalized_theorem_names = {_normalize_name(t) for t in all_theorem_names}

    for def_name, def_file in all_def_names.items():
        if def_name in skip_names or len(def_name) <= 2:
            continue

        # Skip type definitions (structures, classes, inductives) — they're
        # covered by being used as types in theorem signatures
        if def_name in all_type_def_names:
            continue

        # Skip test file definitions
        if 'Tests/' in def_file or 'tests/' in def_file:
            continue

        # Signal 1: def name appears in theorem body/signature (cross-file)
        if def_name in theorem_context_ids:
            continue

        # Signal 2: normalized name match (camelCase↔snake_case)
        norm_name = _normalize_name(def_name)
        if any(norm_name in nt for nt in normalized_theorem_names):
            continue

        # Signal 3: original substring match (backward compat)
        name_lower = def_name.lower()
        if any(name_lower in t.lower() for t in all_theorem_names):
            continue

        # Classify: outside TCB (IO file) vs genuine gap
        if def_file in io_files:
            result['outside_tcb_defs'].append({'name': def_name, 'file': def_file})
        else:
            result['uncovered_defs'].append({'name': def_name, 'file': def_file})

    return result


# ─── Hypothesis Coupling Analysis ─────────────────────────────

def analyze_coupling(project_dir, scan):
    """Analyze coupling between formal theorems (*Spec.lean) and tests.

    Returns dict with coupling metrics: spec files, theorem count,
    bridge status, #check coverage, coupled/uncoupled lists.
    """
    spec_files = []
    spec_theorems = []

    for fi in scan['files']:
        path = fi['path']
        if path.endswith('Spec.lean') and 'Tests/' not in path:
            spec_files.append(path)
            full_path = project_dir / path
            try:
                content = full_path.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for m in re.finditer(
                r'^(theorem|lemma)\s+(\w+)', content, re.MULTILINE,
            ):
                spec_theorems.append({'name': m.group(2), 'file': path})

    # Check for Tests/Bridge.lean
    bridge_path = project_dir / 'Tests' / 'Bridge.lean'
    bridge_exists = bridge_path.exists()
    checked_names = set()

    if bridge_exists:
        try:
            bridge_content = bridge_path.read_text(encoding='utf-8')
            for m in re.finditer(r'#check\s+@?(\w+)', bridge_content):
                checked_names.add(m.group(1))
        except (OSError, UnicodeDecodeError):
            pass

    # Scan all Tests/ files for references to spec theorems
    test_dir = project_dir / 'Tests'
    test_references = set()
    if test_dir.exists():
        for lean_file in sorted(test_dir.rglob('*.lean')):
            if '.lake' in str(lean_file):
                continue
            try:
                content = lean_file.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for t in spec_theorems:
                if t['name'] in content:
                    test_references.add(t['name'])

    # Classify
    coupled = []
    uncoupled = []
    for t in spec_theorems:
        if t['name'] in checked_names or t['name'] in test_references:
            coupled.append(t)
        else:
            uncoupled.append(t)

    total = len(spec_theorems)
    ratio = round(len(coupled) / total * 100) if total > 0 else 0

    return {
        'spec_files': spec_files,
        'spec_theorems_total': total,
        'bridge_exists': bridge_exists,
        'checked_count': len(checked_names),
        'coupled': coupled,
        'uncoupled': uncoupled,
        'coupling_ratio': ratio,
    }


# ─── Text Report Generator ───────────────────────────────────────

def generate_report(arch, readme, benchmarks, scan, coupling=None,
                    spec_audit=None, theorems_path=None):
    """Generate human-readable autopsy report."""
    out = []

    title = readme.get('title', 'Unknown Project')
    subtitle = readme.get('subtitle', '')
    out.append(f'{"═" * 60}')
    out.append(f' AUTOPSIA: {title}')
    if subtitle:
        out.append(f' {subtitle[:80]}')
    out.append(f'{"═" * 60}')
    out.append('')

    # ── Overview
    t = scan['totals']
    out.append('── OVERVIEW ──')
    out.append(f'  Lean files:  {t["files"]}')
    out.append(f'  LOC:         {t["loc"]:,}')
    out.append(f'  Theorems:    {t["theorems"]}')
    out.append(f'  Lemmas:      {t["lemmas"]}')
    out.append(f'  Defs:        {t["defs"]}')
    out.append(f'  Structures:  {t["structures"]}')
    out.append(f'  Inductives:  {t["inductives"]}')
    out.append(f'  Classes:     {t["classes"]}')
    out.append(f'  Instances:   {t["instances"]}')
    out.append(f'  @[simp]:     {t["simp_attrs"]}')
    out.append(f'  #eval:       {t["evals"]}')
    out.append(f'  slim_check:  {t["slim_check"]}')
    out.append('')

    # ── Verification status
    sorry_n = t['sorry']
    axiom_n = t['axioms']
    if sorry_n == 0 and axiom_n == 0:
        out.append('  VERIFICATION: ZERO SORRY, ZERO AXIOMS')
    else:
        if sorry_n > 0:
            out.append(f'  SORRY:   {sorry_n} pending')
        if axiom_n > 0:
            out.append(f'  AXIOMS:  {axiom_n} found')
    out.append('')

    # ── Theorem density
    if t['loc'] > 0:
        density = (t['theorems'] + t['lemmas']) / t['loc']
        out.append(f'  Theorem density: {density:.4f} thm/LOC')
        if density < 0.01:
            out.append('  (low — mostly operational code)')
        elif density < 0.03:
            out.append('  (moderate — mixed spec + implementation)')
        else:
            out.append('  (high — spec-heavy codebase)')
        out.append('')

    # ── Specification Hygiene (from spec_audit.py)
    if spec_audit and spec_audit.get("available"):
        out.append('── SPECIFICATION HYGIENE ──')
        t1 = spec_audit.get("tier1", 0)
        t15 = spec_audit.get("tier15", 0)
        t2 = spec_audit.get("tier2", 0)
        t3 = spec_audit.get("tier3", 0)
        t4 = spec_audit.get("tier4", 0)
        total = spec_audit.get("total_theorems", 0)
        blocking = t1 + t15

        out.append(f'  Theorems scanned:              {total}')
        out.append(f'  T1 (vacuity, blocking):        {t1}')
        out.append(f'  T1.5 (identity passes):        {t15}')
        out.append(f'  T2 (weak specs, advisory):     {t2}')
        out.append(f'  T3 (structural, advisory):     {t3}')
        out.append(f'  T4 (no-witness, advisory):     {t4}')

        if blocking == 0:
            out.append('  STATUS: PASS')
        else:
            parts = []
            if t1 > 0:
                parts.append(f'{t1} T1')
            if t15 > 0:
                parts.append(f'{t15} T1.5')
            out.append(f'  STATUS: FAIL ({" + ".join(parts)} blocking)')

        # Show identity passes
        identity_passes = spec_audit.get("identity_passes", [])
        if identity_passes:
            out.append('')
            out.append('  IDENTITY PASSES:')
            for ip in identity_passes[:15]:
                name = ip.get("name", "?")
                field = ip.get("field", "?")
                pattern = ip.get("pattern", "?")
                file = ip.get("file", "?")
                line = ip.get("line", "?")
                out.append(f'    {name}.{field} {pattern} ({file}:{line})')
            if len(identity_passes) > 15:
                out.append(f'    ... +{len(identity_passes) - 15} more (see THEOREMS.md)')

        # Show T4 issues
        t4_entries = [e for e in spec_audit.get("entries", [])
                      if any("T4" in w for w in e.get("warnings", []))]
        if t4_entries:
            out.append('')
            out.append('  MISSING NON-VACUITY WITNESSES:')
            for entry in t4_entries[:10]:
                out.append(f'    {entry.get("name", "?")} ({entry.get("module", "?")})')
            if len(t4_entries) > 10:
                out.append(f'    ... +{len(t4_entries) - 10} more')

        if theorems_path:
            out.append('')
            out.append(f'  THEOREMS.md: {theorems_path}')

        out.append('')
    elif spec_audit:
        out.append('── SPECIFICATION HYGIENE ──')
        out.append(f'  SKIPPED ({spec_audit.get("warning", "unavailable")})')
        out.append('')

    # ── Documentation status
    out.append('── DOCUMENTATION ──')
    out.append(f'  README.md:        {"FOUND" if readme["found"] else "MISSING"}')
    out.append(f'  ARCHITECTURE.md:  {"FOUND" if arch["found"] else "MISSING"}')
    out.append(f'  BENCHMARKS.md:    {"FOUND" if benchmarks["found"] else "MISSING"}')
    if benchmarks['found']:
        out.append(f'    Has criteria:   {"YES" if benchmarks["has_criteria"] else "NO"}')
        out.append(f'    Has results:    {"YES" if benchmarks["has_results"] else "NO"}')
    out.append('')

    # ── Claims from README
    if readme['found'] and readme['claims']:
        out.append('── CLAIMS (from README.md) ──')
        # Group by type
        by_type = defaultdict(list)
        for c in readme['claims']:
            by_type[c['type']].append(c)
        for ctype, claims in sorted(by_type.items()):
            out.append(f'  [{ctype}]')
            for c in claims[:5]:  # limit per type
                out.append(f'    L{c["line"]}: {c["text"][:120]}')
        out.append('')

    # ── DAG Structure
    if arch.get('dag_nodes'):
        dag_src = arch.get('dag_source', 'ARCHITECTURE.md')
        out.append(f'── DAG STRUCTURE (source: {dag_src}) ──')
        completed = sum(1 for n in arch['dag_nodes'] if n['status'] == 'completed')
        total = len(arch['dag_nodes'])
        pct = completed / total * 100 if total > 0 else 0
        bar_len = 20
        filled = int(pct / 100 * bar_len)
        bar = '\u25a0' * filled + '\u25a1' * (bar_len - filled)
        out.append(f'  [{bar}] {completed}/{total} nodes ({pct:.0f}%)')
        out.append('')

        for ntype in ['FUND', 'CRIT', 'PARALELO', 'HOJA']:
            type_nodes = [n for n in arch['dag_nodes'] if n['type'] == ntype]
            if type_nodes:
                out.append(f'  {ntype}:')
                for n in type_nodes:
                    icon = '\u2713' if n['status'] == 'completed' else '\u25cb'
                    deps = f' (deps: {", ".join(n["deps"])})' if n['deps'] else ''
                    # Enrich with metrics from dag.json
                    metrics = n.get('metrics', {})
                    if metrics:
                        m_loc = metrics.get('loc', 0)
                        m_thm = metrics.get('theorems', 0)
                        m_sorry = metrics.get('sorry', 0)
                        m_tag = f' [{m_loc} LOC, {m_thm}T'
                        if m_sorry > 0:
                            m_tag += f', {m_sorry} sorry'
                        m_tag += ']'
                    else:
                        m_tag = ''
                    out.append(f'    {icon} {n["name"]}{deps}{m_tag}')
        out.append('')

        # Property coverage from dag.json
        nodes_with_props = [n for n in arch['dag_nodes'] if n.get('properties')]
        if nodes_with_props:
            total_props = sum(n['properties'].get('total', 0) for n in nodes_with_props)
            total_pass = sum(n['properties'].get('passing', 0) for n in nodes_with_props)
            total_fail = sum(n['properties'].get('failing', 0) for n in nodes_with_props)
            total_nr = sum(n['properties'].get('not_runnable', 0) for n in nodes_with_props)
            out.append('  SLIMCHECK PROPERTIES:')
            out.append(f'    Total: {total_props} | Passing: {total_pass} | Failing: {total_fail} | Not runnable: {total_nr}')
            for n in nodes_with_props:
                p = n['properties']
                if p.get('total', 0) > 0:
                    out.append(f'    {n["name"]}: {p.get("passing",0)}/{p["total"]} passing')
            out.append('')

        # Incomplete FUND/CRIT
        incomplete = [n for n in arch['dag_nodes']
                      if n['type'] in ('FUND', 'CRIT') and n['status'] != 'completed']
        if incomplete:
            out.append('  INCOMPLETE FOUNDATIONAL/CRITICAL NODES:')
            for n in incomplete:
                out.append(f'    - {n["name"]} ({n["type"]})')
            out.append('')

    # ── Blocks
    if arch['found'] and arch['blocks']:
        out.append('── BLOCKS ──')
        for b in arch['blocks']:
            icon = '\u2713' if b['completed'] else '\u25cb'
            out.append(f'  {icon} Block {b["number"]}: {b["content"][:100]}')
        out.append('')

    # ── Components
    if arch['found'] and arch['components']:
        out.append('── COMPONENTS ──')
        for c in arch['components']:
            out.append(f'  {c["name"]:40s} | {c["files"]:>3} files | {c["loc"]:>6} LOC | {c["extra"][:40]}')
        out.append('')

    # ── Sorry locations
    if scan['sorry_locations']:
        out.append('── SORRY PENDIENTES ──')
        for s in scan['sorry_locations']:
            out.append(f'  {s["file"]}:{s["line"]}  {s["text"][:100]}')
        out.append('')

    # ── Axiom locations
    if scan['axiom_locations']:
        out.append('── AXIOMS ──')
        for a in scan['axiom_locations']:
            out.append(f'  {a["file"]}: axiom {a["name"]}')
        out.append('')

    # ── Uncovered defs
    if scan['uncovered_defs']:
        out.append('── DEFINITIONS WITHOUT THEOREM COVERAGE ──')
        out.append(f'  ({len(scan["uncovered_defs"])} definitions with no theorem reference found)')
        by_file = defaultdict(list)
        for d in scan['uncovered_defs']:
            by_file[d['file']].append(d['name'])
        for f in sorted(by_file):
            names = by_file[f]
            out.append(f'  {f}:')
            for name in names[:8]:
                out.append(f'    - {name}')
            if len(names) > 8:
                out.append(f'    ... +{len(names) - 8} more')
        out.append('')

    # ── Outside TCB defs (IO files with no theorems — informational)
    if scan.get('outside_tcb_defs'):
        out.append('── OUTSIDE TCB (IO files, no theorems — by design) ──')
        out.append(f'  ({len(scan["outside_tcb_defs"])} definitions in unverified IO files)')
        by_file = defaultdict(list)
        for d in scan['outside_tcb_defs']:
            by_file[d['file']].append(d['name'])
        for f in sorted(by_file):
            names = by_file[f]
            out.append(f'  {f}:')
            for name in names[:8]:
                out.append(f'    - {name}')
            if len(names) > 8:
                out.append(f'    ... +{len(names) - 8} more')
        out.append('')

    # ── Hypothesis coupling
    if coupling and coupling['spec_theorems_total'] > 0:
        out.append('── HYPOTHESIS COUPLING ──')
        out.append(f'  Spec files:         {len(coupling["spec_files"])}')
        out.append(f'  Formal theorems:    {coupling["spec_theorems_total"]}')
        bridge_str = 'FOUND' if coupling['bridge_exists'] else 'NOT FOUND'
        out.append(f'  Tests/Bridge.lean:  {bridge_str}')
        out.append(f'  #check coverage:    {coupling["checked_count"]}/{coupling["spec_theorems_total"]}')
        out.append(f'  Coupling ratio:     {coupling["coupling_ratio"]}%')
        if coupling['uncoupled']:
            out.append('  UNCOUPLED THEOREMS:')
            for t in coupling['uncoupled'][:15]:
                out.append(f'    - {t["name"]} ({t["file"]})')
            if len(coupling['uncoupled']) > 15:
                out.append(f'    ... +{len(coupling["uncoupled"]) - 15} more')
        out.append('')

    # ── File breakdown
    out.append('── FILE BREAKDOWN (top 15 by LOC) ──')
    sorted_files = sorted(scan['files'], key=lambda f: f['loc'], reverse=True)
    for fi in sorted_files[:15]:
        sorry_mark = f'  [{fi["sorry"]} sorry]' if fi['sorry'] > 0 else ''
        sc_mark = f'  [slim_check]' if fi.get('slim_check', 0) > 0 else ''
        out.append(
            f'  {fi["loc"]:>5} LOC  '
            f'{fi["theorems"]:>3} thm  '
            f'{fi["lemmas"]:>3} lem  '
            f'{fi["defs"]:>3} def  '
            f'{fi["path"]}{sorry_mark}{sc_mark}'
        )
    out.append('')

    # ── Phases
    if arch['found'] and arch['phases']:
        out.append('── PHASES ──')
        for p in arch['phases']:
            sub = f' Subfase {p["subfase"]}' if p.get('subfase') else ''
            out.append(f'  Fase {p["fase"]}{sub}: {p["name"]}')
        out.append('')

    # ── Versions
    if arch['found'] and arch['versions']:
        out.append('── VERSION HISTORY ──')
        for v in arch['versions']:
            out.append(f'  v{v["version"]} ({v["date"]}): {v["highlights"][:100]}')
        out.append('')

    # ── README sections summary (for LLM claim analysis)
    if readme['found'] and readme['sections']:
        out.append('── README SECTIONS ──')
        for s in readme['sections']:
            preview = s['content'][:150].replace('\n', ' ').strip()
            if preview:
                out.append(f'  [{s["header"]}] {preview}...' if len(s['content']) > 150 else f'  [{s["header"]}] {preview}')
        out.append('')

    # ── Existing #eval (potential property seeds)
    if scan['eval_locations']:
        out.append('── EXISTING #eval (candidates for SlimCheck conversion) ──')
        for e in scan['eval_locations'][:20]:
            out.append(f'  {e["file"]}:{e["line"]}  {e["text"][:100]}')
        if len(scan['eval_locations']) > 20:
            out.append(f'  ... +{len(scan["eval_locations"]) - 20} more')
        out.append('')

    return '\n'.join(out)


# ─── Spec Audit Runner ────────────────────────────────────────────

def run_spec_audit(project_dir):
    """Run spec_audit.py and return structured results."""
    if not SPEC_AUDIT_SCRIPT.exists():
        return {"available": False, "warning": "spec_audit.py not found"}

    cmd = [sys.executable, str(SPEC_AUDIT_SCRIPT), "--project", str(project_dir), "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()
        if output:
            data = json.loads(output)
            return {
                "available": True,
                "tier1": data.get("tier1_issues", 0),
                "tier15": data.get("tier15_issues", 0),
                "tier2": data.get("tier2_issues", 0),
                "tier3": data.get("tier3_issues", 0),
                "tier4": data.get("tier4_issues", 0),
                "total_theorems": data.get("total_theorems", 0),
                "identity_passes": data.get("identity_passes", []),
                "entries": data.get("entries", []),
            }
        return {"available": False, "warning": f"No output. stderr: {result.stderr[:200]}"}
    except subprocess.TimeoutExpired:
        return {"available": False, "warning": "spec_audit timeout (120s)"}
    except Exception as e:
        return {"available": False, "warning": f"spec_audit error: {e}"}


def generate_theorems_md(project_dir):
    """Run spec_audit.py --generate-registry to create THEOREMS.md."""
    if not SPEC_AUDIT_SCRIPT.exists():
        return None
    cmd = [
        sys.executable, str(SPEC_AUDIT_SCRIPT),
        "--project", str(project_dir),
        "--generate-registry", "--output", "THEOREMS.md",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        theorems_path = project_dir / "THEOREMS.md"
        if theorems_path.exists():
            return str(theorems_path)
    except Exception:
        pass
    return None


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Project autopsy: structural + verification audit',
    )
    parser.add_argument('project_dir', help='Path to project directory')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f'Error: {project_dir} is not a directory', file=sys.stderr)
        sys.exit(1)

    # Gather data
    arch = parse_architecture(project_dir / 'ARCHITECTURE.md')
    dag = parse_dag_json(project_dir / 'dag.json')
    readme = parse_readme(project_dir / 'README.md')
    benchmarks = parse_benchmarks(project_dir / 'BENCHMARKS.md')
    scan = scan_lean_files(project_dir)
    coupling = analyze_coupling(project_dir, scan)
    spec_audit = run_spec_audit(project_dir)
    theorems_path = generate_theorems_md(project_dir) if spec_audit.get("available") else None

    # Prefer dag.json over ARCHITECTURE.md regex for nodes/blocks
    if dag['found']:
        arch['dag_nodes'] = dag['dag_nodes']
        arch['dag_source'] = 'dag.json'
        # Merge blocks: prefer dag.json, keep arch blocks as fallback
        if dag['blocks']:
            arch['blocks'] = dag['blocks']
    else:
        arch['dag_source'] = 'ARCHITECTURE.md' if arch['dag_nodes'] else 'none'

    if args.json:
        report = {
            'project_dir': str(project_dir),
            'architecture': arch,
            'dag_json': dag,
            'readme': readme,
            'benchmarks': benchmarks,
            'scan': scan,
            'coupling': coupling,
            'spec_audit': spec_audit,
            'theorems_md': theorems_path,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(generate_report(arch, readme, benchmarks, scan, coupling,
                              spec_audit, theorems_path))


if __name__ == '__main__':
    main()
