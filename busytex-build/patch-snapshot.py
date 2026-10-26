# Snapshot points and resume for pdfTeX and XeTeX, patched into the C that web2c generates (pdftex0.c, xetex0.c)
# before it is compiled (and native pgfmath, at the end of this file). TeX's state lives in linear memory, and at the top of the main loop (`big_switch`, label 60
# in maincontrol) no live state sits in C locals: a copy of memory and of the job's files taken there can be resumed
# later by calling maincontrol() again. The worker takes the copies (Module.clearsnapPoint) and resumes from the
# latest one whose input hasn't changed (patch-worker-snapshot.js).
#   - clearsnap_<e>_setup(mode, beginline): before a run; mode 1 turns the points on, beginline is the main file's
#     \begin{document} line (the first point comes once TeX reads past it, the next ones after each shipped page).
#   - clearsnap_<e>_grow(bytes): grows memory through Emscripten (which keeps its views of memory current), so a copy
#     larger than a fresh engine's memory fits.
#   - clearsnap_<e>_resume(mainpos): after the worker restored a copy, moves the main file to mainpos (where that file's
#     text continues; stdio's read-ahead is dropped) and finishes the job as mainbody does, without \everyjob.
# Each point also reports where TeX is in the main file (ftell: what it has read, not stdio's read-ahead).
# LuaTeX's main loop is hand-written C (luatexdir/tex/maincontrol.c), patched the same way: the point at the top of
# its loop, and a resume that finishes as its mainbody does.
#   python3 patch-snapshot.py pdftex|xetex|luatex <path to pdftex0.c|xetex0.c|luatexdir/tex/maincontrol.c>
import os, re, sys

engine, path = sys.argv[1], sys.argv[2]
e = engine
# Patch the file web2c generated, kept as .orig, so a changed patch applies cleanly.
if not os.path.exists(path + '.orig'):
    os.rename(path, path + '.orig')
s = open(path + '.orig').read()
MARK = '/* Clearsnap snapshot points */'
# The main file's stdio stream, and whether TeX holds nothing read from it beyond that stream's position (XeTeX keeps
# one character back for UTF-16 input).
MAINFILE = {'pdftex': ('inputfile[1]', '1'),
            'xetex': ('(inputfile[1] ? inputfile[1]->f : NULL)', '(inputfile[1] && inputfile[1]->savedChar == -1)')}.get(e)

if e == 'luatex':
    lua = f'''{MARK}
#pragma push_macro("mode")
#undef mode
#include <emscripten.h>
#include <emscripten/heap.h>
#pragma pop_macro("mode")
EM_JS(void, clearsnap_luatex_point, (int kind, int pages, int mainpos), {{ if (Module.clearsnapPoint) Module.clearsnapPoint(kind, pages, mainpos); }});
int clearsnap_luatex_mode = 0, clearsnap_luatex_beginline = 0x7fffffff;
static int clearsnap_luatex_state = 0, clearsnap_luatex_pages = 0, clearsnap_luatex_resuming = 0;
static int clearsnap_luatex_mainpos(void) {{ return in_open >= 1 && input_file[1] ? (int) ftell(input_file[1]) : -1; }}
static void clearsnap_luatex_tick(void) {{
  if (clearsnap_luatex_resuming) {{ clearsnap_luatex_resuming = 0; return; }}
  if (clearsnap_luatex_state == 0 && in_open == 1 && line > clearsnap_luatex_beginline) {{
    clearsnap_luatex_state = 1; clearsnap_luatex_pages = total_pages; clearsnap_luatex_point(0, total_pages, clearsnap_luatex_mainpos()); return;
  }}
  if (total_pages != clearsnap_luatex_pages) {{ clearsnap_luatex_pages = total_pages; clearsnap_luatex_point(1, total_pages, clearsnap_luatex_mainpos()); }}
}}
EMSCRIPTEN_KEEPALIVE void clearsnap_luatex_setup(int on, int begin) {{ /* LuaTeX's headers define `mode` */
  clearsnap_luatex_mode = on; clearsnap_luatex_beginline = begin > 0 ? begin : 0x7fffffff;
  clearsnap_luatex_state = 0; clearsnap_luatex_pages = 0; clearsnap_luatex_resuming = 0;
}}
EMSCRIPTEN_KEEPALIVE int clearsnap_luatex_grow(unsigned int bytes) {{ return emscripten_resize_heap(bytes); }}
EMSCRIPTEN_KEEPALIVE void clearsnap_luatex_resume(int mainpos) {{
  if (mainpos >= 0 && in_open >= 1 && input_file[1]) fseek(input_file[1], mainpos, SEEK_SET);
  clearsnap_luatex_resuming = 1;
  main_control();
  flush_node(text_dir_ptr);
  final_cleanup();
  close_files_and_terminate();
  do_final_end();
}}

'''
    start = s.index('void main_control(void)\n{')
    body = s[start:]
    ej = '    if (equiv(every_job_loc) != null) {'
    loop = '    while (1) {\n        if (main_control_state == goto_skip_token) {'
    assert body.count(ej) >= 1 and body.index(ej) < body.index(loop), 'main_control has changed shape'
    body = body.replace(ej, '    if (!clearsnap_luatex_resuming && equiv(every_job_loc) != null) {', 1)
    body = body.replace(loop, '    while (1) {\n        if (clearsnap_luatex_mode && main_control_state != goto_skip_token) clearsnap_luatex_tick();\n'
                              '        if (main_control_state == goto_skip_token) {', 1)
    open(path, 'w').write(s[:start] + lua + body)
    os.utime(path)
    print(f'patched {path}')
    sys.exit(0)

head = f'''{MARK}
#include <emscripten.h>
#include <emscripten/heap.h>
EM_JS(void, clearsnap_{e}_point, (int kind, int pages, int mainpos), {{ if (Module.clearsnapPoint) Module.clearsnapPoint(kind, pages, mainpos); }});
int clearsnap_{e}_mode = 0, clearsnap_{e}_beginline = 0x7fffffff;
static int clearsnap_{e}_state = 0, clearsnap_{e}_pages = 0, clearsnap_{e}_resuming = 0;
static int clearsnap_{e}_mainpos(void) {{ return inopen >= 1 && {MAINFILE[0]} && {MAINFILE[1]} ? (int) ftell({MAINFILE[0]}) : -1; }}
static void clearsnap_{e}_tick(void) {{
  if (clearsnap_{e}_resuming) {{ clearsnap_{e}_resuming = 0; return; }}
  if (clearsnap_{e}_state == 0 && inopen == 1 && line > clearsnap_{e}_beginline) {{
    clearsnap_{e}_state = 1; clearsnap_{e}_pages = totalpages; clearsnap_{e}_point(0, totalpages, clearsnap_{e}_mainpos()); return;
  }}
  if (totalpages != clearsnap_{e}_pages) {{ clearsnap_{e}_pages = totalpages; clearsnap_{e}_point(1, totalpages, clearsnap_{e}_mainpos()); }}
}}
EMSCRIPTEN_KEEPALIVE void clearsnap_{e}_setup(int mode, int beginline) {{
  clearsnap_{e}_mode = mode; clearsnap_{e}_beginline = beginline > 0 ? beginline : 0x7fffffff;
  clearsnap_{e}_state = 0; clearsnap_{e}_pages = 0; clearsnap_{e}_resuming = 0;
}}
EMSCRIPTEN_KEEPALIVE int clearsnap_{e}_grow(unsigned int bytes) {{ return emscripten_resize_heap(bytes); }}
void maincontrol ( void ) ;
EMSCRIPTEN_KEEPALIVE void clearsnap_{e}_resume(int mainpos) {{
  if (mainpos >= 0 && inopen >= 1 && {MAINFILE[0]}) fseek({MAINFILE[0]}, mainpos, SEEK_SET);
  clearsnap_{e}_resuming = 1;
  maincontrol () ;
  finalcleanup () ;
  closefilesandterminate () ;
  fflush ( stdout ) ;
  readyalready = 0 ;
  if ( ( history != 0 ) && ( history != 1 ) ) uexit ( 1 ) ; else uexit ( 0 ) ;
}}
'''

start = s.index('\nmaincontrol ( void ) \n')
start = s.rindex('\nvoid', 0, start)
body = s[start:]
everyjob = re.search(r'  if \( eqtb \[[0-9L]+ \]\.hh \.v\.RH != -268435455L \) \n  begintokenlist', body)
loop = body.index('  lab60: getxtoken () ;')
assert everyjob and everyjob.start() < loop, 'maincontrol has changed shape'
body = body[:loop] + f'  lab60: if ( clearsnap_{e}_mode ) clearsnap_{e}_tick () ; getxtoken () ;' + body[loop + len('  lab60: getxtoken () ;'):]
body = body[:everyjob.start()] + f'  if ( !clearsnap_{e}_resuming && eqtb' + body[everyjob.start() + len('  if ( eqtb'):]
s = s[:start] + '\n' + head + body

# Native pgfmath (../native/pgfmath.c, used by ../fastpaths/pgfmath.tex and fpu.tex): \pdfstrcmp (XeTeX: \strcmp)
# with a first argument starting clearsnapnative gives pgfmath's or its fpu's result for the tokens in the second
# (cspm_run says which forms there are), or F when pgfmath's own code has to run. The evaluator reads the tokens
# and the registers they name itself.
native = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'native', 'pgfmath.c')).read()
native = native[:native.index('#ifdef CSPM_TEST')]
c = {'pdftex': dict(flag=4095, div=256, single=257, aint=73, adim=74, nd=1, start='strstart[s]', end='strstart[s + 1]'),
     'xetex': dict(flag=0x1FFFFFF, div=0x200000, single=1 + 0x110000, aint=74, adim=75, nd=0,
                   start='strstart[(s) - 65536L]', end='strstart[(s + 1) - 65536L]')}[e]
NULL = '-268435455L'
hook = native + f'''
static int clearsnap_pm_pending; static char clearsnap_pm_out[CSPM_LEN + 8], clearsnap_pm_m[1024];
static int clearsnap_pm_magic(strnumber s) {{   /* a first argument starting "clearsnapnative", kept as a C string */
  static const char m[] = "clearsnapnative"; poolpointer i = {c['start']}, j = {c['end']}; int k;
  if (j - i < (int) sizeof m - 1 || j - i >= (int) sizeof clearsnap_pm_m) return 0;
  for (k = 0; k < (int) sizeof m - 1; k++) if (strpool[i + k] != m[k]) return 0;
  for (k = 0; k < j - i; k++) {{ int ch = strpool[i + k]; if (ch <= 0 || ch > 126) return 0; clearsnap_pm_m[k] = (char) ch; }}
  clearsnap_pm_m[j - i] = 0;
  return 1;
}}
static void clearsnap_pm_run(halfword p) {{
  static cspm_tok toks[512]; int n = 0;
  while (p != {NULL} && n < 512) {{
    halfword t = zmem[p].hh.v.LH; cspm_tok k = {{ CSPM_CHAR, 0, 0, 0 }};
    if (t >= {c['flag']}) {{
      halfword cs = t - {c['flag']}; int cmd = zeqtb[cs].hh.b0;
      k.kind = CSPM_OTHER;
      if (cs >= {c['single']} && cmd == {c['adim']}) {{ k.kind = CSPM_DIMEN; k.val = zeqtb[zeqtb[cs].hh.v.RH].cint; }}
      if (cs >= {c['single']} && cmd == {c['aint']}) {{ k.kind = CSPM_COUNT; k.val = zeqtb[zeqtb[cs].hh.v.RH].cint; }}
    }} else {{ k.cat = t / {c['div']}; k.ch = t % {c['div']}; }}
    toks[n++] = k; p = zmem[p].hh.v.RH;
  }}
  clearsnap_pm_pending = 1;
  if (p != {NULL} || !cspm_run(clearsnap_pm_m, toks, n, {c['nd']}, clearsnap_pm_out, sizeof clearsnap_pm_out)) strcpy(clearsnap_pm_out, "F");
}}
static void clearsnap_pm_print(void) {{ const char *q; clearsnap_pm_pending = 0; for (q = clearsnap_pm_out; *q; q++) printchar(*q); }}
'''
inc = f'#include "{e}d.h"\n'
assert s.count(inc) == 1, 'include'
s = s.replace(inc, inc + hook, 1)
cmp_at = '  s1 = tokenstostring ( defref ) ;\n  deletetokenref ( defref ) ;\n  curcs = savecurcs ;\n'
assert s.count(cmp_at) == 1, 'comparestrings has changed shape'
s = s.replace(cmp_at, cmp_at + '''  if ( clearsnap_pm_magic ( s1 ) ) {
    if ( scantoks ( false , true ) != 0 ) ;
    clearsnap_pm_run ( zmem [defref ].hh .v.RH ) ;
    deletetokenref ( defref ) ;
    flushstr ( s1 ) ;
    curval = 0 ;
    curvallevel = 0 ;
    return ;
  }
''', 1)
a = s.index('\nconvtoks ( void ) \n'); b = s.index('\n}', a)
m = list(re.finditer(r'case 18 : \n(\s*)printint \( curval \) ;', s[a:b]))
assert len(m) == 1, 'convtoks has changed shape'
m = m[0]
s = s[:a + m.start()] + f'case 18 : \n{m.group(1)}if ( clearsnap_pm_pending ) clearsnap_pm_print () ; else printint ( curval ) ;' + s[a + m.end():]

open(path, 'w').write(s)
os.utime(path)
print(f'patched {path}')
# Research builds only (CLEARSNAP_STATS=1): pdfTeX also counts macro calls and redefinitions (../research).
if os.environ.get('CLEARSNAP_STATS') and e == 'pdftex':
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'research', 'patch-macrostats.py'), path], check=True)
