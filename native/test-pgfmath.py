# Differential test of native/pgfmath.c against pgfmath itself: random expressions (and the ones given), evaluated by
# pgfmath in pdfLaTeX and by the C evaluator; every expression the C code answers must give exactly pgfmath's
# \pgfmathresult and units flag, with no TeX error. Prints the mismatches and how many the C code left to pgfmath.
#   python3 test-pgfmath.py [count] [seed]          (TEXINPUTS picks the pgf version, e.g. a 3.1.11a copy)
import os, random, re, subprocess, sys, tempfile

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix='cspm-', dir=os.environ.get('TMPDIR'))

REGS = [('rega', 'd', 98304), ('regb', 'd', -3276800), ('regc', 'd', 1), ('regd', 'd', 1073741823 // 3),
        ('rege', 'd', 0), ('cnta', 'c', 7), ('cntb', 'c', -12), ('cntc', 'c', 0), ('cntd', 'c', 40000)]

def number():
    r = random.random()
    if r < 0.3: return str(random.randint(0, 20))
    if r < 0.55: return '%d.%s' % (random.randint(0, 99), ''.join(random.choice('0123456789') for _ in range(random.randint(1, 7))))
    if r < 0.65: return '.' + ''.join(random.choice('0123456789') for _ in range(random.randint(1, 5)))
    if r < 0.72: return str(random.randint(100, 20000))
    if r < 0.78: return '0.000%d' % random.randint(1, 99)
    if r < 0.82: return '%d.' % random.randint(0, 50)
    return '%d.%d' % (random.randint(0, 9), random.randint(0, 9))

FUNCS = ['sin', 'cos', 'tan', 'deg', 'rad', 'abs', 'exp', 'ln', 'log10', 'log2', 'sqrt']
def operand(depth):
    r = random.random()
    if os.environ.get('FUNCS') and depth < 3 and r < 0.2:
        k = random.random()
        if k < 0.1: return random.choice(['pi', 'e'])
        if k < 0.2: return number() + 'r'
        f = random.choice(FUNCS)
        arg = expr(depth + 1) if random.random() < 0.6 else number()
        if f == 'exp' and random.random() < 0.7: arg = random.choice(['-', '']) + '%d.%d' % (random.randint(0, 9), random.randint(0, 99))
        if k < 0.3: return f + ' ' + number()
        return f + '(' + arg + ')'
    if depth < 3 and r < 0.15: return '(' + expr(depth + 1) + ')'
    if r < 0.22: return '-' + operand(depth)
    if r < 0.30: return '\\' + random.choice(REGS)[0]
    if r < 0.35: return number() + '\\' + random.choice([g for g in REGS if g[1] == 'd'])[0]
    if r < 0.50: return number() + random.choice(['pt', 'bp', 'cm', 'mm', 'in', 'pc', 'dd', 'cc', 'sp', 'nd', 'nc'])
    return number()

def expr(depth=0):
    e = operand(depth)
    for _ in range(random.randint(0, 3)):
        e += random.choice(['+', '-', '*', '/', '*', '/', '^']) + operand(depth)
    return e

GIVEN = ['sqrt(2)', 'sqrt(16)', 'sqrt(0.25)', 'sqrt(12345)', 'sqrt(0)', 'sqrt(16383)', 'sqrt(0.00002)', 'sqrt(9999.99)', 'sqrt(-1)', 'sin(30)', 'cos(60)', 'sin 30', 'sin(30.5)*2', '2*30r', 'exp(-1.5^2)', 'tan(90)', 'tan(45)', 'exp(9.8)', 'exp(-10)',
         'pi*2', 'e^2', '-sin(-30)', 'sin(1e2)', 'sin30', 'cos (60)', 'abs(-\\rega)', 'deg(pi)', 'rad(180)', '1+2', '2*3pt', '1/3', '10/4', '-2^2', '(1+2)*3', '1/0.3', '7/0.75', '2^-2', '2^0.5', '0.25*-2.0*-2.0',
         '16000+1000', '16000pt+1000pt', '1/0', '{1+2}', '{{2}}', '(2', '2)', '2*(3+4)/5', '100/7', '5/0.00002',
         '1e3', '010+1', '0x10', '2*3^2', '2^3^2', '-(-3)', '+-+3', '3 + 4', '3 . 5 + 1', '\\rega', '\\cnta+1', '2\\cnta',
         '\\cnta\\rega', '\\rega*\\rega', '1em+1pt', '\\regd*4', '9999/0.0001', '1/7*7', '0.5^-3', '(-2)^3', '(-2)^-3']
def focused():
    def num():
        r = random.random()
        if r < 0.2: return '%d.%05d' % (random.randint(0, 3), random.randint(0, 99999))
        if r < 0.4: return '0.%05d' % random.randint(1, 99999)
        if r < 0.55: return str(random.randint(1, 16383))
        if r < 0.7: return '%d.%d' % (random.randint(1, 16383), random.randint(0, 99999))
        if r < 0.8: return '0.0000%d' % random.randint(1, 9)
        return '%d.%d' % (random.randint(0, 99), random.randint(0, 99))
    sign = lambda: random.choice(['', '', '-'])
    k = random.random()
    if k < 0.6: return sign() + num() + '/' + sign() + num()
    if k < 0.8: return sign() + num() + '*' + sign() + num()
    return sign() + num() + '^' + str(random.choice([-3, -2, -1, 0, 1, 2, 3, 4, 5, 7]))
def sqrtcase():
    k = random.random()
    if k < 0.3: return 'sqrt(%d.%05d)' % (random.randint(0, 9), random.randint(0, 99999))
    if k < 0.6: return 'sqrt(%d.%03d)' % (random.randint(10, 16383), random.randint(0, 999))
    if k < 0.8: return 'sqrt(0.%05d)' % random.randint(1, 99999)
    return 'sqrt(%d)' % random.randint(0, 16383)
exprs = GIVEN + [sqrtcase() if os.environ.get('FOCUS') == 'sqrt' else focused() if os.environ.get('FOCUS') else expr() for _ in range(N)]

# pgfmath
lines = [r'\documentclass{article}', r'\usepackage{pgf}', r'\makeatletter']
for n, k, v in REGS:
    lines.append((r'\newdimen\%s \%s=%dsp' if k == 'd' else r'\newcount\%s \%s=%d') % (n, n, v))
lines += [r'\newwrite\out \immediate\openout\out=\jobname.res', r'\begin{document}']
if os.environ.get('TRIG') == 'rad': lines.append(r'\pgfkeys{/pgf/trig format=rad}')
for i, e in enumerate(exprs):
    lines.append(r'\typeout{CSPM-BEGIN %d}\pgfmathparse{%s}\immediate\write\out{%d \ifpgfmathunitsdeclared U\else N\fi\pgfmathresult}\typeout{CSPM-END %d}\leavevmode\par' % (i, e, i, i))
lines += [r'\immediate\closeout\out', r'\end{document}']
open(f'{tmp}/t.tex', 'w').write('\n'.join(lines))
subprocess.run(['pdflatex', '-interaction=nonstopmode', 't.tex'], cwd=tmp, capture_output=True)
tex = {}
for l in open(f'{tmp}/t.res'):
    m = re.match(r'(\d+) (.*)', l.rstrip('\n'))
    if m: tex[int(m.group(1))] = m.group(2)
log = open(f'{tmp}/t.log', errors='replace').read()
errors = set()
cur = None
for l in log.split('\n'):
    m = re.match(r'CSPM-BEGIN (\d+)', l)
    if m: cur = int(m.group(1))
    if l.startswith('CSPM-END'): cur = None
    if l.startswith('!') and cur is not None: errors.add(cur)

# the C evaluator
subprocess.run(['cc', '-O2', '-DCSPM_TEST', '-o', f'{tmp}/cspm', f'{HERE}/pgfmath.c'], check=True)
inp = ''.join(f'R {n} {k} {v}\n' for n, k, v in REGS) + ('T 1\n' if os.environ.get('TRIG') == 'rad' else '') + ''.join(f'E {e}\n' for e in exprs)
out = subprocess.run([f'{tmp}/cspm', 'nd'], input=inp, capture_output=True, text=True).stdout.split('\n')

bad = answered = 0
for i, e in enumerate(exprs):
    c = out[i]
    if c == 'FALLBACK': continue
    answered += 1
    t = tex.get(i)
    if i in errors or t != c:
        bad += 1
        if bad <= 40: print(f'MISMATCH {e!r}: pgfmath {t!r}{" (TeX error)" if i in errors else ""}, C {c!r}')
clean = [e for i, e in enumerate(exprs) if out[i] == 'FALLBACK' and i not in errors]
if os.environ.get('SHOW_FALLBACKS'):
    for e in clean[:int(os.environ['SHOW_FALLBACKS'])]: print('FALLBACK (pgfmath had no error):', e)
print(f'{len(exprs)} expressions: C answered {answered}, left {len(exprs) - answered} to pgfmath '
      f'({len(clean)} of them without a TeX error), {bad} mismatches')
sys.exit(1 if bad else 0)
