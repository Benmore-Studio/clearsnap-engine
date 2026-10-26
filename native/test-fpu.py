# Differential test of native/pgfmath.c's fpu against pgfmath's fpu library in pdfLaTeX: random expressions parsed with
# /pgf/fpu on (with x and y bound as pgfplots binds them), and the operations pgfplots calls directly
# (\pgfmathfloatparsenumber, add, subtract, multiply, divide, tofixed, neg, abs) on random numbers. Every answer the C
# code gives must be pgfmath's \pgfmathresult exactly (and the units flag), with no TeX error.
#   python3 test-fpu.py [count] [seed]          (TRIG=rad for the radian trig format)
import os, random, re, subprocess, sys, tempfile

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix='cspm-fpu-', dir=os.environ.get('TMPDIR'))

def digits(k): return ''.join(random.choice('0123456789') for _ in range(k))
def number():
    r = random.random()
    if r < 0.2: return str(random.randint(0, 50))
    if r < 0.45: return '%d.%s' % (random.randint(0, 999), digits(random.randint(1, 6)))
    if r < 0.55: return '0.%s%s' % ('0' * random.randint(0, 6), digits(random.randint(1, 4)))
    if r < 0.65: return '%s%se%s%d' % (random.randint(1, 9), random.choice(['', '.' + digits(random.randint(1, 4))]), random.choice(['', '-', '+']), random.randint(0, 12))
    if r < 0.72: return str(random.randint(100, 9999999))
    if r < 0.78: return '.' + digits(random.randint(1, 5))
    if r < 0.82: return '%d.' % random.randint(0, 99)
    if r < 0.86: return '0%d.%s' % (random.randint(0, 9), digits(3))
    return '%d.%s0' % (random.randint(1, 9), digits(2))

def flt():
    s, m, e = random.choice([1, 1, 2, 2, 0]), '%d.%s' % (random.randint(1, 9), digits(random.randint(1, 5))), random.randint(-8, 8)
    return '0Y0.0e0]' if s == 0 else '%dY%se%d]' % (s, m, e)

FUNCS = ['sin', 'cos', 'tan', 'deg', 'rad', 'abs', 'exp', 'ln', 'log10', 'log2', 'sqrt']
def operand(depth):
    r = random.random()
    if depth < 3 and r < 0.12: return '(' + expr(depth + 1) + ')'
    if r < 0.2: return '-' + operand(depth)
    if r < 0.32: return flt()
    if r < 0.42: return random.choice(['x', 'y', 'pi', 'e'])
    if depth < 3 and r < 0.55:
        f = random.choice(FUNCS)
        arg = expr(depth + 1) if random.random() < 0.5 else number()
        if f == 'exp' and random.random() < 0.7: arg = random.choice(['-', '']) + '%d.%d' % (random.randint(0, 9), random.randint(0, 99))
        return f + '(' + arg + ')'
    if r < 0.6: return '%d.%s' % (random.randint(0, 99), digits(2)) + random.choice(['pt', 'cm', 'bp'])   # (pgfmath's fpu loops on a length past \maxdimen)
    return number()

def expr(depth=0):
    e = operand(depth)
    for _ in range(random.randint(0, 3)):
        op = random.choice(['+', '-', '*', '/', '*', '^'])
        e += op + (str(random.randint(-4, 6)) if op == '^' else operand(depth))   # (pgfmath's fpu hangs after an overflow)
    return e

XV, YV = '2Y1.25e0]', '1Y7.5e-1]'
GIVEN = ['1.5*2', '2.5', 'exp(-1)', 'sin(30)', '1e-3*2', '1Y2.0e0]+3', 'exp(-x^2-y^2)', 'pi', 'x*e', '-x^2', 'x^3',
         'exp(-x^2-y^2)*cos(deg(1*x))', '1Y1.0e0] + 0.5*0.25', '1/0', '0/0', 'x/0', '2^-3', '2^0.5', '0^0.5',
         '1e5*1e5*1e5', '123456789*987654321', 'sin(1e10)', 'cos(-725)', 'tan(90)', 'exp(30)', 'exp(-30)']
exprs = GIVEN + [('sqrt(%s)' % number()) if os.environ.get('FOCUS') == 'sqrt' else expr() for _ in range(N)]
ops = []
for _ in range(N):
    k = random.choice(['parse', 'parse', 'add', 'sub', 'mul', 'div', 'tofixed', 'neg', 'abs', 'ln', 'sqrt'])
    if k == 'parse': ops.append((k, [random.choice(['', '-', '+']) + number()]))
    elif k in ('tofixed', 'neg', 'abs', 'ln', 'sqrt'): ops.append((k, [flt()]))
    else: ops.append((k, [flt(), flt()]))
ops += [('parse', ['1Y2.0e0]']), ('parse', ['0Y0.0e0]']), ('parse', ['nan']), ('parse', ['-inf']), ('parse', ['0e5']),
        ('parse', ['00.0050']), ('add', ['1Y1.0e9]', '1Y1.0e0]']), ('div', ['1Y1.0e0]', '0Y0.0e0]']), ('tofixed', ['1Y1.234567e12]'])]
MAC = {'parse': r'\pgfmathfloatparsenumber', 'add': r'\pgfmathfloatadd@', 'sub': r'\pgfmathfloatsubtract@',
       'mul': r'\pgfmathfloatmultiply@', 'div': r'\pgfmathfloatdivide@', 'tofixed': r'\pgfmathfloattofixed@',
       'neg': r'\pgfmathfloatneg@', 'abs': r'\pgfmathfloatabs@', 'ln': r'\pgfmathfloatln@', 'sqrt': r'\pgfmathfloatsqrt@'}

# pgfmath's fpu can loop for good after an overflow error, so the cases run 100 to a document, each with a time limit;
# a document that does not finish leaves its cases unanswered by pgfmath (and so not compared).
HEAD = [r'\documentclass{article}', r'\usepackage{pgf}', r'\usepgflibrary{fpu}', r'\makeatletter',
        r'\newwrite\out \immediate\openout\out=\jobname.res', r'\begin{document}', r'\pgfkeys{/pgf/fpu}']
if os.environ.get('TRIG') == 'rad': HEAD.append(r'\pgfkeys{/pgf/trig format=rad}')
HEAD += [r'\def\xval{%s}\def\yval{%s}' % (XV, YV),
         r'\pgfmathdeclarefunction*{x}{0}{\edef\pgfmathresult{\xval}}\pgfmathdeclarefunction*{y}{0}{\edef\pgfmathresult{\yval}}']
cases = []
for i, e in enumerate(exprs):
    cases.append(r'\typeout{CSPM-BEGIN %d}\pgfmathparse{%s}\immediate\write\out{%d \ifpgfmathunitsdeclared U\else N\fi\pgfmathresult}\typeout{CSPM-END %d}\leavevmode\par' % (i, e, i, i))
for j, (k, args) in enumerate(ops):
    i = len(exprs) + j
    cases.append(r'\typeout{CSPM-BEGIN %d}%s%s\immediate\write\out{%d \pgfmathresult}\typeout{CSPM-END %d}\leavevmode\par' % (i, MAC[k], ''.join('{%s}' % a for a in args), i, i))
tex, errors, hung, skipped = {}, set(), 0, set()
for c0 in range(0, len(cases), 100):
    open(f'{tmp}/t.tex', 'w').write('\n'.join(HEAD + cases[c0:c0 + 100] + [r'\immediate\closeout\out', r'\end{document}']))
    try:
        subprocess.run(['pdflatex', '-interaction=nonstopmode', 't.tex'], cwd=tmp, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        hung += 1
        for i in range(c0, min(c0 + 100, len(cases))): skipped.add(i)
        continue
    for l in open(f'{tmp}/t.res'):
        m = re.match(r'(\d+) (.*)', l.rstrip('\n'))
        if m: tex[int(m.group(1))] = m.group(2)
    cur = None
    for l in open(f'{tmp}/t.log', errors='replace').read().split('\n'):
        m = re.match(r'CSPM-BEGIN (\d+)', l)
        if m: cur = int(m.group(1))
        if l.startswith('CSPM-END'): cur = None
        if l.startswith('!') and cur is not None: errors.add(cur)
if hung: print(f'({hung} documents of 100 cases did not finish in pgfmath and were skipped)')

subprocess.run(['cc', '-O2', '-DCSPM_TEST', '-o', f'{tmp}/cspm', f'{HERE}/pgfmath.c'], check=True)
inp = ('T 1\n' if os.environ.get('TRIG') == 'rad' else '') + f'F 1\nB x={XV};y={YV}\n' + ''.join(f'E {e}\n' for e in exprs) + \
      ''.join(f'O {k} {",".join(a)}\n' for k, a in ops)
out = subprocess.run([f'{tmp}/cspm', 'nd'], input=inp, capture_output=True, text=True).stdout.split('\n')

bad = answered = clean = 0
items = [('E', e) for e in exprs] + [('O', f'{k} {",".join(a)}') for k, a in ops]
for i, (kind, what) in enumerate(items):
    c = out[i]
    if i in skipped: continue
    if c == 'FALLBACK':
        if i not in errors: clean += 1
        continue
    answered += 1
    t = tex.get(i)
    if kind == 'O': t = None if t is None else t
    want = t if kind == 'O' else t
    if i in errors or want != c:
        bad += 1
        if bad <= 40: print(f'MISMATCH {kind} {what!r}: pgfmath {want!r}{" (TeX error)" if i in errors else ""}, C {c!r}')
print(f'{len(items)} cases: C answered {answered}, left {len(items) - answered} to pgfmath ({clean} without a TeX error), {bad} mismatches')
sys.exit(1 if bad else 0)
