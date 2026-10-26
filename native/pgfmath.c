/* Clearsnap: pgfmath's expression parser for arithmetic and its common functions, in C, with exactly the results
   pgfmath's TeX code gives. pgfmath works on numbers written as text and on TeX's integer arithmetic (\pgfmath@x=#1pt,
   \advance, a decimal factor times a dimension, \divide, \the), so this follows its code step by step on the same
   integers: TeX's scan_dimen, round_decimals, xn_over_d, mult_and_add, x_over_n and print_scaled, and pgfmath's own
   parser (operator stack, precedences, unary minus, groups, function names), neg, add, subtract, multiply, divide
   (with its reciprocal), pow with an integer exponent, sin, cos and tan (its table of cosines), deg, rad, the postfix
   r, abs, exp, pi and e. Anything else (other functions, comparisons, scientific or octal numbers, font-dependent
   units) and anything that would make TeX report an error returns 0, and pgfmath's own code runs instead.
   The fpu library (pgflibraryfpu.code.tex) is followed the same way: its float texts, number parser, add, subtract,
   multiply, divide, tofixed, mod, trig functions, exp and integer powers, and its parser mode.
   Built into the engine by ../busytex-build/patch-snapshot.py (cspm_run, reached through \pdfstrcmp in pdfTeX and
   \strcmp in XeTeX) and natively for the differential tests (test-pgfmath.py, test-fpu.py; -DCSPM_TEST). */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { CSPM_CHAR = 0, CSPM_DIMEN = 1, CSPM_COUNT = 2, CSPM_OTHER = 3 };
typedef struct { int kind; int ch; int cat; int32_t val; } cspm_tok;

#define CSPM_LEN 160
#define CSPM_STACK 64
#define UNITY 65536
#define MAX_DIMEN 07777777777
typedef struct { char s[CSPM_LEN]; } cspm_val;

static int cspm_arith;     /* TeX's arith_error */
static int32_t cspm_rem;   /* TeX's remainder */
static int cspm_fail;      /* something pgfmath's own code has to do */

/* 32-bit integer arithmetic as TeX's (web2c's int32 wraps). */
static int32_t cspm_w_mul(int32_t a, int32_t b) { return (int32_t)((uint32_t)a * (uint32_t)b); }
static int32_t cspm_w_add(int32_t a, int32_t b) { return (int32_t)((uint32_t)a + (uint32_t)b); }

static int32_t cspm_xn_over_d(int32_t x, int32_t n, int32_t d) {
  int positive = 1; int32_t t, u, v;
  if (x < 0) { x = -x; positive = 0; }
  t = cspm_w_mul(x % 32768, n);
  u = cspm_w_add(cspm_w_mul(x / 32768, n), t / 32768);
  v = cspm_w_add(cspm_w_mul(u % d, 32768), t % 32768);
  if (u / d >= 32768) cspm_arith = 1;
  else u = cspm_w_add(cspm_w_mul(32768, u / d), v / d);
  if (positive) { cspm_rem = v % d; return u; }
  cspm_rem = -(v % d); return -u;
}

static int32_t cspm_mult_and_add(int32_t n, int32_t x, int32_t y, int32_t max) {
  if (n < 0) { x = -x; n = -n; }
  if (n == 0) return y;
  if (x <= (max - y) / n && -x <= (max + y) / n) return cspm_w_add(cspm_w_mul(n, x), y);
  cspm_arith = 1; return 0;
}
#define cspm_nx_plus_y(n, x, y) cspm_mult_and_add(n, x, y, MAX_DIMEN)
#define cspm_mult_integers(n, x) cspm_mult_and_add(n, x, 0, 017777777777)

static int32_t cspm_x_over_n(int32_t x, int32_t n) {
  int negative = 0; int32_t r;
  if (n == 0) { cspm_arith = 1; cspm_rem = x; return 0; }
  if (n < 0) { x = -x; n = -n; negative = 1; }
  if (x >= 0) { r = x / n; cspm_rem = x % n; }
  else { r = -((-x) / n); cspm_rem = -((-x) % n); }
  if (negative) cspm_rem = -cspm_rem;
  return r;
}

static int32_t cspm_round_decimals(const int *dig, int k) {
  int32_t a = 0;
  while (k > 0) { k--; a = (a + dig[k] * 131072) / 10; }
  return (a + 1) / 2;
}

/* \the of a dimension without "pt" (pgfmath's \pgfmath@tonumber): TeX's cspm_print_scaled. */
static void cspm_print_scaled(int32_t s, char *out) {
  char buf[40]; int n = 0; int32_t delta;
  if (s < 0) { out[n++] = '-'; s = -s; }
  n += sprintf(out + n, "%d", s / UNITY);
  out[n++] = '.';
  s = 10 * (s % UNITY) + 5; delta = 10;
  do {
    if (delta > UNITY) s = s + 0100000 - 50000;
    out[n++] = (char)('0' + s / UNITY); s = 10 * (s % UNITY); delta *= 10;
  } while (s > delta);
  out[n] = 0; (void)buf;
}

/* TeX reading a number at *p: signs, then an integer (scan_int) or a point, then a decimal fraction (17 digits count).
   Sets the sign, integer part and fraction (in 2^-16); 0 for what TeX would report (missing or too big a number). */
static int cspm_scan_unsigned(const char **pp, int32_t *ip, int32_t *frac) {
  const char *p = *pp; int dig[17], k = 0; int32_t v = 0;
  if (*p != '.') {
    if (*p < '0' || *p > '9') return 0;              /* Missing number */
    while (*p >= '0' && *p <= '9') {
      int d = *p - '0';
      if (v >= 214748364 && (v > 214748364 || d > 7)) return 0;   /* Number too big */
      v = v * 10 + d; p++;
    }
  }
  *frac = 0;
  if (*p == '.') {
    p++;
    while (*p >= '0' && *p <= '9') { if (k < 17) dig[k++] = *p - '0'; p++; }
    *frac = cspm_round_decimals(dig, k);
  }
  *ip = v; *pp = p;
  return 1;
}
static int cspm_scan_number(const char **pp, int *negative, int32_t *ip, int32_t *frac) {
  const char *p = *pp;
  *negative = 0;
  while (*p == '-' || *p == '+') { if (*p == '-') *negative = !*negative; p++; }
  *pp = p;
  return cspm_scan_unsigned(pp, ip, frac);
}

static int cspm_attach_sign(int32_t v, int negative, int32_t *out) {
  if (cspm_arith || v >= 010000000000 || v <= -010000000000) return 0;   /* Dimension too large */
  *out = negative ? -v : v;
  return 1;
}

/* \dimen=<number><unit>: the unit is pt, in, pc, cm, mm, bp, dd, cc, sp (and nd, nc in pdfTeX). */
static int cspm_nd;   /* the engine knows nd and nc */
static int cspm_scan_dimen_unit(const char *num, const char *unit, int32_t *out) {
  const char *p = num; int negative; int32_t v, f, nu = 0, de = 0;
  cspm_arith = 0;
  if (!cspm_scan_number(&p, &negative, &v, &f) || *p) return 0;
  if (!strcmp(unit, "pt")) ;
  else if (!strcmp(unit, "in")) nu = 7227, de = 100;
  else if (!strcmp(unit, "pc")) nu = 12, de = 1;
  else if (!strcmp(unit, "cm")) nu = 7227, de = 254;
  else if (!strcmp(unit, "mm")) nu = 7227, de = 2540;
  else if (!strcmp(unit, "bp")) nu = 7227, de = 7200;
  else if (!strcmp(unit, "dd")) nu = 1238, de = 1157;
  else if (!strcmp(unit, "cc")) nu = 14856, de = 1157;
  else if (cspm_nd && !strcmp(unit, "nd")) nu = 685, de = 642;
  else if (cspm_nd && !strcmp(unit, "nc")) nu = 1370, de = 107;
  else if (!strcmp(unit, "sp")) return cspm_attach_sign(v, negative, out);
  else return 0;
  if (nu) {
    v = cspm_xn_over_d(v, nu, de);
    f = (nu * f + 0200000 * cspm_rem) / de;
    v = v + f / 0200000; f = f % 0200000;
  }
  if (v >= 040000) cspm_arith = 1; else v = v * UNITY + f;
  return cspm_attach_sign(v, negative, out);
}
static int cspm_scan_pt(const char *num, int32_t *out) { return cspm_scan_dimen_unit(num, "pt", out); }

/* \dimen=<number>\dimenregister: signs, then the register itself or a factor times it. */
static int cspm_scan_factor_dimen(const char *num, int32_t v, int32_t *out) {
  const char *p = num; int negative = 0; int32_t ip = 0, f = 0;
  cspm_arith = 0;
  while (*p == '-' || *p == '+') { if (*p == '-') negative = !negative; p++; }
  if (!*p) return cspm_attach_sign(v, negative, out);
  if (!cspm_scan_unsigned(&p, &ip, &f) || *p) return 0;
  return cspm_attach_sign(cspm_nx_plus_y(ip, v, cspm_xn_over_d(v, f, 0200000)), negative, out);
}

/* \count=<text>: an integer at the start of the text (scan_int), and the rest of it. */
static int cspm_scan_int_prefix(const char *s, int32_t *out, const char **rest) {
  const char *p = s; int negative = 0; int32_t v = 0;
  while (*p == '-' || *p == '+') { if (*p == '-') negative = !negative; p++; }
  if (*p < '0' || *p > '9') return 0;
  while (*p >= '0' && *p <= '9') {
    int d = *p - '0';
    if (v >= 214748364 && (v > 214748364 || d > 7)) return 0;
    v = v * 10 + d; p++;
  }
  *out = negative ? -v : v; *rest = p;
  return 1;
}

static int cspm_set_val(cspm_val *r, const char *s) {
  if (strlen(s) >= CSPM_LEN) return 0;
  strcpy(r->s, s); return 1;
}
static int cspm_returnone(int32_t x, cspm_val *r) {      /* pgfmath's \pgfmath@cspm_returnone: \pgfmath@x\pgfmath@x, \the */
  char b[40];
  if (x >= 010000000000 || x <= -010000000000) return 0;
  cspm_print_scaled(x, b); return cspm_set_val(r, b);
}
static int cspm_cat(char *out, const char *a, const char *b) {
  if (strlen(a) + strlen(b) >= CSPM_LEN) return 0;
  strcpy(out, a); strcat(out, b); return 1;
}

static int cspm_f_neg(const cspm_val *a, cspm_val *r) {
  char t[CSPM_LEN]; int32_t x;
  if (!cspm_cat(t, "-", a->s) || !cspm_scan_pt(t, &x)) return 0;
  return cspm_returnone(x, r);   /* (neg prints \pgfmath@x directly; it is within range) */
}
static int cspm_f_add(const cspm_val *a, const cspm_val *b, cspm_val *r, int sub) {
  int32_t x, y;
  if (!cspm_scan_pt(a->s, &x) || !cspm_scan_pt(b->s, &y)) return 0;
  x = cspm_w_add(x, sub ? -y : y);
  return cspm_returnone(x, r);
}
static int cspm_f_mul(const cspm_val *a, const cspm_val *b, cspm_val *r) {
  int32_t x, y; char f[40];
  if (!cspm_scan_pt(a->s, &x) || !cspm_scan_pt(b->s, &y)) return 0;
  cspm_print_scaled(y, f);
  if (!cspm_scan_factor_dimen(f, x, &x)) return 0;
  return cspm_returnone(x, r);
}

/* pgfmath's \pgfmathreciprocal@ (#1 is the text of a number), on "<\the x without pt>0000000" split as #1.#2#3#4#5#6#7. */
static int cspm_f_reciprocal(const char *a, cspm_val *r) {
  int32_t x, y, ca, cb, i1; char temp[48], ip[24], fr[48], buf[64]; const char *dot, *rest; int i;
  if (!cspm_scan_pt(a, &x) || x == 0) return 0;
  cspm_print_scaled(x, temp);
  dot = strchr(temp, '.');
  if (dot - temp >= (long)sizeof ip) return 0;
  memcpy(ip, temp, dot - temp); ip[dot - temp] = 0;                 /* #1 */
  snprintf(fr, sizeof fr, "%s0000000", dot + 1);                    /* #2#3#4#5#6 are its first five */
  snprintf(buf, sizeof buf, "%.5s", fr);
  if (!cspm_scan_int_prefix(buf, &ca, &rest) || *rest) return 0;
  if (!cspm_scan_int_prefix(ip, &i1, &rest) || *rest) return 0;
  if (ca == 0) {
    if (!cspm_scan_pt("1", &x)) return 0;
    cspm_arith = 0; x = cspm_x_over_n(x, i1); if (cspm_arith) return 0;
  } else {
    snprintf(buf, sizeof buf, i1 > 100 ? "%s%.3s" : "%s%.5s", ip, fr);
    if (!cspm_scan_int_prefix(buf, &ca, &rest) || *rest) return 0;
    cspm_arith = 0; cb = cspm_x_over_n(1000000000, ca); if (cspm_arith) return 0;
    ca = cb;
    ca = cspm_x_over_n(ca, 10000);
    snprintf(buf, sizeof buf, "%d", ca); if (!cspm_scan_pt(buf, &x)) return 0;
    cspm_arith = 0; ca = cspm_mult_integers(ca, -10000); if (cspm_arith) return 0;
    cb = cspm_w_add(cb, ca);
    snprintf(buf, sizeof buf, "%d", cb); if (!cspm_scan_pt(buf, &y)) return 0;
    if (i1 > 100) y = cspm_x_over_n(y, 1000000);
    else for (i = 0; i < 4; i++) if (!cspm_scan_factor_dimen(".1", y, &y)) return 0;
    x = cspm_w_add(x, y);
  }
  return cspm_returnone(x, r);
}

/* pgfmath's \pgfmathdivide@cspm_dimenbyten: the text of the number with its point one digit to the left. */
static int cspm_dimenbyten(int32_t *y) {
  char t[40], b[64]; char *dot; int32_t ip, a, bq; const char *rest;
  cspm_print_scaled(*y, t);
  dot = strchr(t, '.'); *dot = 0;
  if (!cspm_scan_int_prefix(t, &ip, &rest) || *rest) return 0;
  a = cspm_x_over_n(ip, 10); bq = a;
  a = cspm_w_mul(a, -10); a = cspm_w_add(a, ip);
  snprintf(b, sizeof b, "%d.%d%s", bq, a, dot + 1);
  return cspm_scan_pt(b, y);
}

/* pgfmath's \pgfmathdivide@advance@last@digit on the result text. */
static int cspm_advance_last_digit(char *res) {
  char *dot = strchr(res, '.'); char c[6]; int i, k; int32_t ya, xa; char b[48];
  if (!dot) return 0;
  for (i = 0; i < 5; i++) c[i] = dot[1 + i] ? dot[1 + i] : 'C';
  for (i = 0; i < 5; i++) if (!dot[1 + i]) break;     /* (the text never has a C in it) */
  k = i;
  if (!cspm_scan_pt(res, &ya)) return 0;
  { static const char *steps[] = { "1", "0.1", "0.01", "0.001", "0.0001", "0.00001" };
    if (!cspm_scan_pt(steps[k], &xa)) return 0; }
  ya = cspm_w_add(ya, xa);
  cspm_print_scaled(ya, b);
  { char *bd = strchr(b, '.'); if (!strcmp(bd + 1, "0")) bd[1] = 0; }   /* \pgfmath@tonumber@notrailingzero */
  if (strlen(b) >= CSPM_LEN) return 0;
  strcpy(res, b); (void)c;
  return 1;
}

static int cspm_f_div(const cspm_val *a, const cspm_val *b, cspm_val *r) {
  int32_t x, y, ca, xa; char sign[4] = "", yt[48], res[CSPM_LEN], t[CSPM_LEN + 8]; const char *rest;
  if (!cspm_scan_pt(a->s, &x) || !cspm_scan_pt(b->s, &y)) return 0;
  if (y == 0) return 0;                                   /* pgfmath reports it */
  cspm_print_scaled(y, yt);                                    /* \c@pgfmath@counta\the\pgfmath@y, the rest into \pgfmath@xa */
  if (!cspm_scan_int_prefix(yt, &ca, &rest)) return 0;
  { char tail[48]; snprintf(tail, sizeof tail, "%s", rest);   /* ".5" and then pt */
    if (!cspm_scan_pt(tail, &xa)) return 0; }
  if (xa == 0) {
    cspm_arith = 0; x = cspm_x_over_n(x, ca); if (cspm_arith) return 0;
  } else {
    if (x < 0) { strcat(sign, "-"); x = -x; }
    if (y < 0) { strcat(sign, "-"); y = -y; }
    if (y < UNITY) {
      char yy[40]; cspm_val rc;
      cspm_print_scaled(y, yy);
      if (!cspm_f_reciprocal(yy, &rc)) return 0;
      if (!cspm_cat(t, sign, rc.s) || !cspm_scan_factor_dimen(t, x, &x)) return 0;
    } else {
      int period = 1, guard = 0;
      strcpy(res, "0"); ca = 0;
      for (;;) {
        if (++guard > 1000) return 0;
        if (!(1 < x) || !(1 < y)) break;                  /* \pgfmath@small@number pt is 1sp */
        if (y > x) {
          if (period) { if (strlen(res) + 2 >= CSPM_LEN) return 0; strcat(res, "."); period = 0; }
          if (!cspm_dimenbyten(&y)) return 0;
          if (y > x) { if (strlen(res) + 2 >= CSPM_LEN) return 0; strcat(res, "0"); }
        } else {
          int32_t cb, ya; int append = 1;
          ca = x; cb = y; ca = cspm_x_over_n(ca, cb);
          cspm_arith = 0; ya = cspm_nx_plus_y(ca, y, 0);
          if (cspm_arith || ya >= 010000000000 || ya <= -010000000000) return 0;
          x = cspm_w_add(x, -ya);
          if (!period && ca > 9) {
            if (!cspm_advance_last_digit(res)) return 0;
            ca -= 10;
            if (ca == 0) append = 0;
          }
          if (append) { char d[16]; snprintf(d, sizeof d, "%d", ca); if (strlen(res) + strlen(d) >= CSPM_LEN) return 0; strcat(res, d); }
        }
      }
      if (!cspm_cat(t, sign, res)) return 0;
      if (!cspm_scan_pt(t, &x)) return 0;
    }
  }
  return cspm_returnone(x, r);
}

static int cspm_f_pow(const cspm_val *a, const cspm_val *b, cspm_val *r) {
  int32_t xa, xb, x, ca; char t[48]; const char *rest;
  if (!cspm_scan_pt(a->s, &xa) || !cspm_scan_pt(b->s, &xb)) return 0;
  if (xa == 0) { x = xb == 0 ? UNITY : 0; return cspm_returnone(x, r); }
  cspm_print_scaled(xb, t);
  if (!cspm_scan_int_prefix(t, &ca, &rest) || !cspm_scan_pt(rest, &x)) return 0;   /* the fraction goes into \pgfmath@x */
  if (x != 0) return 0;                                                  /* ln and exp: pgfmath's code */
  if (ca < 0) {
    cspm_val rc; ca = -ca;
    if (!cspm_f_reciprocal(a->s, &rc) || !cspm_scan_pt(rc.s, &xa)) return 0;
  }
  x = UNITY;
  while (ca > 0) {
    char f[40];
    if (ca & 1) { cspm_print_scaled(x, f); if (!cspm_scan_factor_dimen(f, xa, &x)) return 0; }
    if (ca > 1) { cspm_print_scaled(xa, f); if (!cspm_scan_factor_dimen(f, xa, &xa)) return 0; }
    ca /= 2;
  }
  return cspm_returnone(x, r);
}

/* pgfmath's cosine table (\pgfmath@cos@0 to \pgfmath@cos@181, pgfmathfunctions.trigonometric.code.tex). */
static const char *const cspm_cos[182] = {
  "1.00000", "0.99985", "0.99939", "0.99863", "0.99756", "0.99619", "0.99452", "0.99255",
  "0.99027", "0.98769", "0.98481", "0.98163", "0.97815", "0.97437", "0.97030", "0.96593",
  "0.96126", "0.95630", "0.95106", "0.94552", "0.93969", "0.93358", "0.92718", "0.92050",
  "0.91355", "0.90631", "0.89879", "0.89101", "0.88295", "0.87462", "0.86603", "0.85717",
  "0.84805", "0.83867", "0.82904", "0.81915", "0.80902", "0.79864", "0.78801", "0.77715",
  "0.76604", "0.75471", "0.74314", "0.73135", "0.71934", "0.70711", "0.69466", "0.68200",
  "0.66913", "0.65606", "0.64279", "0.62932", "0.61566", "0.60182", "0.58779", "0.57358",
  "0.55919", "0.54464", "0.52992", "0.51504", "0.50000", "0.48481", "0.46947", "0.45399",
  "0.43837", "0.42262", "0.40674", "0.39073", "0.37461", "0.35837", "0.34202", "0.32557",
  "0.30902", "0.29237", "0.27564", "0.25882", "0.24192", "0.22495", "0.20791", "0.19081",
  "0.17365", "0.15643", "0.13917", "0.12187", "0.10453", "0.08716", "0.06976", "0.05234",
  "0.03490", "0.01745", "0.00000", "-0.01745", "-0.03490", "-0.05234", "-0.06976", "-0.08716",
  "-0.10453", "-0.12187", "-0.13917", "-0.15643", "-0.17365", "-0.19081", "-0.20791", "-0.22495",
  "-0.24192", "-0.25882", "-0.27564", "-0.29237", "-0.30902", "-0.32557", "-0.34202", "-0.35837",
  "-0.37461", "-0.39073", "-0.40674", "-0.42262", "-0.43837", "-0.45399", "-0.46947", "-0.48481",
  "-0.50000", "-0.51504", "-0.52992", "-0.54464", "-0.55919", "-0.57358", "-0.58779", "-0.60182",
  "-0.61566", "-0.62932", "-0.64279", "-0.65606", "-0.66913", "-0.68200", "-0.69466", "-0.70711",
  "-0.71934", "-0.73135", "-0.74314", "-0.75471", "-0.76604", "-0.77715", "-0.78801", "-0.79864",
  "-0.80902", "-0.81915", "-0.82904", "-0.83867", "-0.84805", "-0.85717", "-0.86603", "-0.87462",
  "-0.88295", "-0.89101", "-0.89879", "-0.90631", "-0.91355", "-0.92050", "-0.92718", "-0.93358",
  "-0.93969", "-0.94552", "-0.95106", "-0.95630", "-0.96126", "-0.96593", "-0.97030", "-0.97437",
  "-0.97815", "-0.98163", "-0.98481", "-0.98769", "-0.99027", "-0.99255", "-0.99452", "-0.99619",
  "-0.99756", "-0.99863", "-0.99939", "-0.99985", "-1.00000", "-0.99985",
};

static int cspm_trig;   /* pgfmath's trig format: 0 degrees, 1 radians */

/* pgfmath's sin (cos shifted by 90 degrees) and cos: the angle brought into 0 to 180 degrees, then the table,
   interpolated between whole degrees. */
static int cspm_f_cossin(const cspm_val *a, cspm_val *r, int sine) {
  int32_t x, xa, ca, t; char b[40]; const char *rest;
  if (!cspm_scan_pt(a->s, &x)) return 0;
  if (cspm_trig && !cspm_scan_factor_dimen("57.29577", x, &x)) return 0;
  if (sine) { if (!cspm_scan_pt("-90", &t)) return 0; x = cspm_w_add(x, t); }
  cspm_print_scaled(x, b);
  if (!cspm_scan_int_prefix(b, &ca, &rest)) return 0;
  ca = cspm_x_over_n(ca, 360);
  cspm_arith = 0; ca = cspm_mult_integers(ca, -360); if (cspm_arith) return 0;
  snprintf(b, sizeof b, "%d", ca); if (!cspm_scan_pt(b, &t)) return 0;
  x = cspm_w_add(x, t);
  if (x < 0) x = -x;
  if (!(x < 180 * UNITY)) x = cspm_w_add(-x, 360 * UNITY);
  cspm_print_scaled(x, b);
  if (!cspm_scan_int_prefix(b, &ca, &rest) || !cspm_scan_pt(rest, &xa)) return 0;
  if (ca < 0 || ca > 180) return 0;
  if (xa == 0) { if (!cspm_scan_pt(cspm_cos[ca], &x)) return 0; }
  else {
    x = cspm_w_add(-xa, UNITY);
    if (!cspm_scan_factor_dimen(cspm_cos[ca], x, &x)) return 0;
    ca++; if (ca == 181) ca = 179;
    if (!cspm_scan_factor_dimen(cspm_cos[ca], xa, &t)) return 0;
    x = cspm_w_add(x, t);
  }
  return cspm_returnone(x, r);
}
static int cspm_f_tan(const cspm_val *a, cspm_val *r) {
  cspm_val c, rc, sn; int32_t x;
  if (!cspm_f_cossin(a, &c, 0) || !cspm_f_reciprocal(c.s, &rc) || !cspm_f_cossin(a, &sn, 1)) return 0;
  if (!cspm_scan_pt(sn.s, &x) || !cspm_scan_factor_dimen(rc.s, x, &x)) return 0;
  return cspm_returnone(x, r);
}
static int cspm_f_scale(const cspm_val *a, cspm_val *r, const char *factor, int divisor) {   /* deg, rad */
  int32_t x;
  if (!cspm_scan_pt(a->s, &x) || !cspm_scan_factor_dimen(factor, x, &x)) return 0;
  if (divisor) x = cspm_x_over_n(x, divisor);
  return cspm_returnone(x, r);
}
static int cspm_f_abs(const cspm_val *a, cspm_val *r) {
  int32_t x;
  if (!cspm_scan_pt(a->s, &x)) return 0;
  if (x < 0) x = -x;
  return cspm_returnone(x, r);
}
/* pgfmath's exp: the series for |a| until the sum stops changing, the reciprocal for a negative a. */
static int cspm_f_exp(const cspm_val *a, cspm_val *r) {
  int32_t x, xa, xb, xc, yc; int counter; char f[40];
  if (!cspm_scan_pt(a->s, &xc)) return 0;
  yc = xc;
  if (xc < -9 * UNITY) x = 1;
  else {
    if (xc < 0) xc = -xc;
    x = UNITY; xa = UNITY; xb = x;
    for (counter = 1;; counter++) {
      if (counter > 100000) return 0;
      xa = cspm_x_over_n(xa, counter);
      cspm_print_scaled(xc, f);
      if (!cspm_scan_factor_dimen(f, xa, &xa)) return 0;
      x = cspm_w_add(x, xa);
      if (x >= 010000000000 || x <= -010000000000) return 0;   /* \ifdim reading it would report it */
      if (x == xb) break;
      xb = x;
    }
    if (yc < 0) {
      cspm_val rc; char t[40];
      cspm_print_scaled(x, t);
      if (!cspm_f_reciprocal(t, &rc) || !cspm_scan_pt(rc.s, &x)) return 0;
    }
  }
  return cspm_returnone(x, r);
}

static int cspm_append(char *d, const char *s) {
  if (strlen(d) + strlen(s) >= CSPM_LEN) return 0;
  strcat(d, s); return 1;
}
/* pgfmath's sqrt: the digits of x (a zero put in front to make pairs) read two at a time, one digit of the root per
   pair from its decision tree on TeX counters, with the point after `target` digits and five digits past it. */
static int cspm_imul(int32_t a, int32_t b, int32_t *out) {     /* \multiply on a count: overflow is an error */
  cspm_arith = 0; *out = cspm_mult_integers(a, b); return !cspm_arith;
}
static int cspm_iscan(const char *t, int32_t *v) { const char *rest; return cspm_scan_int_prefix(t, v, &rest) && !*rest; }
static int cspm_f_sqrt(const cspm_val *a, cspm_val *r) {
  int32_t x, ca, cb, cc, rem, target, d; char t[64], dig[64], root[CSPM_LEN], rs[CSPM_LEN], rems[40]; int nd = 0, i;
  const char *zeros, *dot;
  if (!cspm_scan_pt(a->s, &x) || x < 0) return 0;
  if (x < 10 * UNITY) { zeros = "0"; target = 1; }
  else if (x < 100 * UNITY) { zeros = ""; target = 1; }
  else if (x < 1000 * UNITY) { zeros = "0"; target = 2; }
  else if (x < 10000 * UNITY) { zeros = ""; target = 2; }
  else { zeros = "0"; target = 3; }
  strcpy(t, zeros); cspm_print_scaled(x, t + strlen(t));
  for (dot = t; *dot; dot++) if (*dot != '.') dig[nd++] = *dot;  /* #1#2: the digits without the point */
  if (nd < 2) return 0;
  { char p2[3] = { dig[0], dig[1], 0 }; if (!cspm_iscan(p2, &cb)) return 0; }
  ca = cb > 35 ? (cb > 63 ? (cb > 80 ? 9 : 8) : (cb > 48 ? 7 : 6))
              : (cb > 15 ? (cb > 24 ? 5 : 4) : (cb > 3 ? (cb > 8 ? 3 : 2) : (cb > 0 ? 1 : 0)));
  snprintf(root, sizeof root, "%d", ca); strcpy(rs, root);
  if (!cspm_imul(ca, -ca, &ca)) return 0;
  ca = cspm_w_add(ca, cb);
  snprintf(rems, sizeof rems, "%d", ca);
  i = 2;
  for (;;) {                                                    /* \pgfmath@@@sqrt@ */
    char pair[3] = { 0, 0, 0 }; char ds[2] = { 0, 0 };
    if (i >= nd) { pair[0] = '0'; pair[1] = '0'; }
    else if (i + 1 >= nd) { pair[0] = dig[i]; pair[1] = '0'; i++; }
    else { pair[0] = dig[i]; pair[1] = dig[i + 1]; i += 2; }
    if (strlen(rems) + 3 >= sizeof rems) return 0;
    strcat(rems, pair);
    if (!cspm_iscan(rems, &rem)) return 0;                        /* (\ifnum reading it: too big is an error) */
    if (!cspm_iscan(rs, &ca) || !cspm_imul(ca, 20, &ca)) return 0;
    if (!cspm_imul(ca, 6, &cb)) return 0;
    cb = cspm_w_add(cb, 36);
    if (!cspm_imul(ca, 2, &cc)) return 0;
    if (cb > rem) {
      cb = cspm_w_add(cspm_w_add(cb, -cc), -20);
      if (cb > rem) {
        cb = cspm_w_add(cspm_w_add(cb, -cc), -12);
        if (cb > rem) { cb = cspm_w_add(cspm_w_add(cb, -ca), -3); d = cb > rem ? 0 : 1; }
        else { cb = cspm_w_add(cspm_w_add(cb, ca), 5); d = cb > rem ? 2 : 3; }
      } else { cb = cspm_w_add(cspm_w_add(cb, ca), 9); d = cb > rem ? 4 : 5; }
    } else {
      cb = cspm_w_add(cspm_w_add(cb, cc), 28);
      if (cb > rem) { cb = cspm_w_add(cspm_w_add(cb, -ca), -15); d = cb > rem ? 6 : 7; }
      else { cb = cspm_w_add(cspm_w_add(cb, ca), 17); d = cb > rem ? 8 : 9; }
    }
    ds[0] = (char)('0' + d);
    if (!cspm_append(rs, ds)) return 0;
    ca = cspm_w_add(ca, d);
    if (!cspm_imul(ca, -d, &ca)) return 0;
    ca = cspm_w_add(ca, rem);
    snprintf(rems, sizeof rems, "%d", ca);
    target--;
    if (target == 0) { if (!cspm_append(root, ".")) return 0; }
    if (!cspm_append(root, ds)) return 0;
    if (target == -4) break;
  }
  return cspm_set_val(r, root);
}

/* pgfmath's ln: x brought into 1 to 2 by a power of two (its tree of comparisons, \divide or \multiply), then its
   polynomial in that number, plus the power, times ln 2. */
static int32_t cspm_dim(const char *t) { int32_t v = 0; cspm_scan_pt(t, &v); return v; }
static int cspm_f_ln(const cspm_val *a, cspm_val *r) {
  int32_t x, t; int k = 0; char tmp[40], f[40];
  static const struct { const char *poly; } P[1] = { { 0 } };
  if (!cspm_scan_pt(a->s, &x) || x <= 0) return 0;          /* pgfmath reports it */
  if (x > 2 * UNITY) {
    if (x < 128 * UNITY) {
      if (x < 8 * UNITY) k = x < 4 * UNITY ? 1 : 2;
      else if (x < 32 * UNITY) k = x < 16 * UNITY ? 3 : 4;
      else k = x < 64 * UNITY ? 5 : 6;
    } else if (x < 2048 * UNITY) {
      if (x < 512 * UNITY) k = x < 256 * UNITY ? 7 : 8;
      else k = x < 1024 * UNITY ? 9 : 10;
    } else {
      if (x < 8192 * UNITY) k = x < 4096 * UNITY ? 11 : 12;
      else k = 13;
    }
    x = cspm_x_over_n(x, 1 << k);
  } else if (x < UNITY) {
    if (x > cspm_dim("0.0078125")) {
      if (x > cspm_dim("0.125")) k = x > cspm_dim("0.5") ? 1 : 2;
      else if (x > cspm_dim("0.03125")) k = x > cspm_dim("0.0625") ? 3 : 4;
      else k = x > cspm_dim("0.015625") ? 5 : 6;
    } else if (x > cspm_dim("0.00048828125")) {
      if (x > cspm_dim("0.001953125")) k = x > cspm_dim("0.00390625") ? 7 : 8;
      else k = x > cspm_dim("0.0009765625") ? 9 : 10;
    } else if (x > cspm_dim("0.0001220703125")) k = x > cspm_dim("0.0002441406256") ? 11 : 12;
    else k = 13;
    cspm_arith = 0; x = cspm_nx_plus_y(x, 1 << k, 0); if (cspm_arith) return 0;
    k = -k;
  }
  (void)P;
  cspm_print_scaled(x, tmp);                                    /* \pgfmath@temp */
  if (!cspm_scan_factor_dimen("0.04300521312", x, &x)) return 0;
  x = cspm_w_add(x, cspm_dim("-.4025153233"));
  if (!cspm_scan_factor_dimen(tmp, x, &x)) return 0;
  x = cspm_w_add(x, cspm_dim("1.589480044"));
  if (!cspm_scan_factor_dimen(tmp, x, &x)) return 0;
  x = cspm_w_add(x, cspm_dim("-3.489886985"));
  if (!cspm_scan_factor_dimen(tmp, x, &x)) return 0;
  x = cspm_w_add(x, cspm_dim("5.047861502"));
  if (!cspm_scan_factor_dimen(tmp, x, &x)) return 0;
  x = cspm_w_add(x, cspm_dim("-2.787927935"));
  snprintf(f, sizeof f, "%d", k);
  if (!cspm_scan_pt(f, &t)) return 0;
  x = cspm_w_add(x, t);
  if (!cspm_scan_factor_dimen("0.6931471806", x, &x)) return 0;
  return cspm_returnone(x, r);
}
static int cspm_f_logk(const cspm_val *a, cspm_val *r, const char *factor) {   /* log2, log10 */
  cspm_val l; int32_t x;
  if (!cspm_f_ln(a, &l) || !cspm_scan_pt(l.s, &x) || !cspm_scan_factor_dimen(factor, x, &x)) return 0;
  return cspm_returnone(x, r);
}

/* ---- pgfmath's fpu library (pgflibraryfpu.code.tex, pgfmathfloat.code.tex) ----
   A float is the text "<flags>Y<mantissa>e<exponent>]" (flags 0 zero, 1 positive, 2 negative, 3 nan, 4 +inf, 5 -inf).
   Each operation below does what its macro does with that text and with the basic functions above. */
typedef struct { int s; char m[CSPM_LEN]; int32_t e; } cspm_flt;

static int cspm_fcreate(int s, const char *m, int32_t e, cspm_val *r) {   /* \pgfmathfloatcreate */
  char b[CSPM_LEN + 40];
  if (strlen(m) + 30 >= CSPM_LEN) return 0;
  snprintf(b, sizeof b, "%dY%se%d]", s, m, e);
  return cspm_set_val(r, b);
}
/* \pgfmathfloat@decompose@tok: one flags digit, Y, the mantissa up to the first e, the exponent up to the final ]. */
static int cspm_fsplit(const char *t, cspm_flt *f) {
  size_t L = strlen(t), n; const char *e, *rest; char ex[24];
  if (L < 5 || t[0] < '0' || t[0] > '5' || t[1] != 'Y' || t[L - 1] != ']') return 0;
  e = strchr(t + 2, 'e');
  if (!e || e >= t + L - 1) return 0;
  n = (size_t)(e - (t + 2));
  if (n >= CSPM_LEN) return 0;
  memcpy(f->m, t + 2, n); f->m[n] = 0;
  n = (size_t)((t + L - 1) - (e + 1));
  if (n == 0 || n >= sizeof ex) return 0;
  memcpy(ex, e + 1, n); ex[n] = 0;
  if (!cspm_scan_int_prefix(ex, &f->e, &rest) || *rest) return 0;
  f->s = t[0] - '0';
  return 1;
}

/* \pgfmathfloatparsenumber: the state machine of \pgfflt@impl, one character at a time. */
static int cspm_fparse(const char *s, cspm_val *r) {
  const char *p = s; int S = 1, pending = 0, st; char M[CSPM_LEN] = "", tmp[CSPM_LEN] = "", c1[2] = { 0, 0 };
  int32_t E = 0;
  enum { A, B, C, D, ES, F, G };
  if (*p == '+') p++;
  else if (*p == '-') { S = 2; p++; }
  if (!*p) return 0;                                         /* "empty number" */
  st = A;
  for (;; p++) {
    char c = *p;
    int digit = c >= '1' && c <= '9';
    c1[0] = c;
    if (c == ' ' || c == ',') return 0;                       /* (spaces skipped by TeX, comma as period: pgfmath's code) */
    switch (st) {
      case A:
        if (c == '0') { st = B; continue; }
        if (digit) { strcpy(M, c1); pending = 1; st = D; continue; }
        if (c == '.') { E = -1; st = C; continue; }
        if (c == 'n' || c == 'N') {
          if ((p[1] == 'a' || p[1] == 'A') && (p[2] == 'n' || p[2] == 'N')) return cspm_fcreate(3, "0.0", 0, r);
          return 0;
        }
        if (c == 'i' || c == 'I') {
          if ((p[1] == 'n' || p[1] == 'N') && (p[2] == 'f' || p[2] == 'F')) return cspm_fcreate(S == 1 ? 4 : 5, "0.0", 0, r);
          return 0;
        }
        return 0;
      case B: case C:
        if (c == '0') { if (st == C) E = cspm_w_add(E, -1); continue; }
        if (digit) { strcpy(M, c1); pending = 1; st = st == B ? D : F; continue; }
        if (st == B && c == '.') { E = -1; st = C; continue; }
        if (st == B && c == 'Y') { strcpy(M, "0"); goto lowlevel; }
        if (c == 'e' || c == 'E') { S = 0; strcpy(M, "0.0"); E = 0; goto exponent; }
        if (!c) { S = 0; strcpy(M, "0.0"); E = 0; goto done; }
        return 0;
      case D: case ES:
        if (c == '0') { E = cspm_w_add(E, 1); if (!cspm_append(tmp, "0")) return 0; st = ES; continue; }
        if (digit) {
          E = cspm_w_add(E, 1);
          if (pending) { if (!cspm_append(M, ".")) return 0; pending = 0; }
          if (st == ES) { if (!cspm_append(M, tmp)) return 0; tmp[0] = 0; }
          if (!cspm_append(M, c1)) return 0;
          st = D; continue;
        }
        if (st == D && c == 'Y') goto lowlevel;
        if (c == '.') { st = F; continue; }
        if (c == 'e' || c == 'E') goto exponent;
        if (!c) goto done;
        return 0;
      case F: case G:
        if (c == '0') { if (!cspm_append(tmp, "0")) return 0; st = G; continue; }
        if (digit) {
          if (pending) { if (!cspm_append(M, ".")) return 0; pending = 0; }
          if (!cspm_append(M, tmp) || !cspm_append(M, c1)) return 0;
          tmp[0] = 0; st = F; continue;
        }
        if (c == 'e' || c == 'E') goto exponent;
        if (!c) goto done;
        return 0;
    }
  }
lowlevel:                                                     /* \pgfflt@readlowlevelfloat: <flags>Y<m>e<e>] */
  {
    const char *e = strchr(p + 1, 'e'), *rest; size_t L = strlen(p), n; char ex[24], mm[CSPM_LEN]; int32_t fl, ee;
    if (strlen(M) != 1 || M[0] < '0' || M[0] > '9' || !e || p[L - 1] != ']') return 0;   /* (one flags digit read) */
    if (!cspm_scan_int_prefix(M, &fl, &rest) || *rest) return 0;
    n = (size_t)(e - (p + 1)); if (n >= CSPM_LEN) return 0;
    memcpy(mm, p + 1, n); mm[n] = 0;
    n = (size_t)((p + L - 1) - (e + 1)); if (n == 0 || n >= sizeof ex) return 0;
    memcpy(ex, e + 1, n); ex[n] = 0;
    if (!cspm_scan_int_prefix(ex, &ee, &rest) || *rest) return 0;
    return cspm_fcreate(fl, mm, ee, r);
  }
exponent:                                                     /* \pgfflt@readexponent: an integer, then the end */
  {
    int32_t x; const char *rest;
    if (!cspm_scan_int_prefix(p + 1, &x, &rest) || *rest) return 0;
    E = cspm_w_add(E, x);
  }
done:
  if (pending && !cspm_append(M, ".0")) return 0;
  return cspm_fcreate(S, M, E, r);
}

/* \pgfmathfloattoextentedprecision@a and @b: the mantissa (with 000, for b 00, appended) with its point `shift` digits
   to the right and the exponent lowered by shift; flags 3 to 5 keep the whole float. */
static int cspm_fext(const char *t, int shift, int isb, cspm_flt *f, char *arg) {
  char m[CSPM_LEN + 8]; char *dot;
  if (!cspm_fsplit(t, f)) return 0;
  if (f->s >= 3) { if (strlen(t) >= CSPM_LEN) return 0; strcpy(arg, t); return 1; }
  f->e = cspm_w_add(f->e, -shift);
  if (strlen(f->m) + 4 >= CSPM_LEN) return 0;
  snprintf(m, sizeof m, "%s%s", f->m, isb ? "00" : "000");
  dot = strchr(m, '.');
  if (!dot || (int)strlen(dot + 1) < shift) return 0;
  {
    size_t n = (size_t)(dot - m);
    memcpy(arg, m, n); memcpy(arg + n, dot + 1, shift); arg[n + shift] = 0;
    if (shift) { strcat(arg, "."); strcat(arg, dot + 1 + shift); }
    else strcat(arg, dot);
  }
  return 1;
}
static int cspm_fbasic(int op, const char *a, const char *b, cspm_val *r) {   /* the basic functions, on texts */
  cspm_val x, y;
  if (!cspm_set_val(&x, a) || !cspm_set_val(&y, b)) return 0;
  switch (op) {
    case 0: return cspm_f_add(&x, &y, r, 0);
    case 1: return cspm_f_mul(&x, &y, r);
    default: return cspm_f_div(&x, &y, r);
  }
}
/* \pgfmathfloatadd@shift: the mantissa of the smaller exponent divided down to the larger one. */
static int cspm_fshift(char *arg, int32_t *small, int32_t large) {
  int32_t xa, d = cspm_w_add(large, -*small);
  if (!cspm_scan_pt(arg, &xa)) return 0;
  switch (d) {
    case 0: break;
    case 1: xa = cspm_x_over_n(xa, 10); break;
    case 2: xa = cspm_x_over_n(xa, 100); break;
    case 3: xa = cspm_x_over_n(xa, 1000); break;
    case 4: xa = cspm_x_over_n(xa, 10000); break;
    case 5: xa = cspm_x_over_n(cspm_x_over_n(xa, 10000), 10); break;
    case 6: xa = cspm_x_over_n(cspm_x_over_n(xa, 10000), 100); break;
    case 7: xa = cspm_x_over_n(cspm_x_over_n(xa, 10000), 1000); break;
    case 8: xa = cspm_x_over_n(cspm_x_over_n(xa, 10000), 10000); break;
    default: xa = 0;
  }
  *small = large;
  cspm_print_scaled(xa, arg);
  return 1;
}
static int cspm_fe(const cspm_val *num, int32_t e, cspm_val *r) {      /* \pgfmathfloatqparsenumber{<num>e<e>} */
  char b[CSPM_LEN + 24];
  if (strlen(num->s) + 20 >= sizeof b) return 0;
  snprintf(b, sizeof b, "%se%d", num->s, e);
  return cspm_fparse(b, r);
}
static int cspm_fadd(const char *a, const char *b, cspm_val *r) {
  cspm_flt fa, fb; char arga[CSPM_LEN + 16], argb[CSPM_LEN + 16], t[CSPM_LEN + 16]; int cmp = 1; cspm_val s;
  if (!cspm_fext(a, 2, 0, &fa, arga) || !cspm_fext(b, 2, 1, &fb, argb)) return 0;
  switch (fa.s) {
    case 0: if (!cspm_set_val(r, b)) return 0; cmp = 0; break;
    case 1: break;
    case 2: snprintf(t, sizeof t, "-%s", arga); strcpy(arga, t); break;
    default: cmp = 0; if (!cspm_fcreate(fa.s, "0.0", 0, r)) return 0;
  }
  switch (fb.s) {
    case 0: if (!cspm_set_val(r, a)) return 0; cmp = 0; break;
    case 1: break;
    case 2: snprintf(t, sizeof t, "-%s", argb); strcpy(argb, t); break;
    default: cmp = 0; if (!cspm_fcreate(fb.s, "0.0", 0, r)) return 0;
  }
  if (!cmp) return 1;
  if (fa.e < fb.e) { if (!cspm_fshift(arga, &fa.e, fb.e)) return 0; }
  else if (!cspm_fshift(argb, &fb.e, fa.e)) return 0;
  if (!cspm_fbasic(0, arga, argb, &s)) return 0;
  return cspm_fe(&s, fa.e, r);
}
static int cspm_fneg(const char *a, cspm_val *r) {
  cspm_flt f; static const int to[] = { 0, 2, 1, 3, 5, 4 };
  if (!cspm_fsplit(a, &f)) return 0;
  if (f.s == 0 || f.s == 3) return cspm_set_val(r, a);
  return cspm_fcreate(to[f.s], f.m, f.e, r);
}
static int cspm_fsub(const char *a, const char *b, cspm_val *r) {   /* \pgfmathfloatsubtract@ */
  cspm_flt f; cspm_val nb;
  if (!cspm_fsplit(b, &f)) return 0;
  switch (f.s) {
    case 0: return cspm_set_val(r, a);
    case 1: if (!cspm_fcreate(2, f.m, f.e, &nb)) return 0; return cspm_fadd(a, nb.s, r);
    case 2: if (!cspm_fcreate(1, f.m, f.e, &nb)) return 0; return cspm_fadd(a, nb.s, r);
    default: return cspm_fcreate(f.s, "0.0", 0, r);
  }
}
static int cspm_fabs(const char *a, cspm_val *r) {
  cspm_flt f;
  if (!cspm_fsplit(a, &f)) return 0;
  if (f.s == 2) f.s = 1;
  if (f.s == 5) f.s = 4;
  return cspm_fcreate(f.s, f.m, f.e, r);
}
/* multiply and divide: the flags of the result from a table, the mantissas through the basic function. */
static const signed char cspm_fmul_tab[6][6] = {
  { 0, 0, 0, 0, 0, 0 }, { 0, -1, -2, 3, 4, 5 }, { 0, -2, -1, 3, 5, 4 },
  { 3, 3, 3, 3, 3, 3 }, { 0, 4, 5, 3, 4, 5 }, { 0, 5, 4, 3, 5, 4 } };
static const signed char cspm_fdiv_tab[6][6] = {
  { 0, 0, 0, 0, 0, 0 }, { 4, -1, -2, 3, 0, 0 }, { 5, -2, -1, 3, 0, 0 },
  { 3, 3, 3, 3, 3, 3 }, { 4, 4, 5, 3, 4, 5 }, { 5, 5, 4, 3, 5, 4 } };
static int cspm_fmuldiv(const char *a, const char *b, cspm_val *r, int div) {
  cspm_flt fa, fb, fr; char arga[CSPM_LEN + 16], argb[CSPM_LEN + 16]; int k; cspm_val s, q;
  if (!cspm_fext(a, 1, 0, &fa, arga) || !cspm_fext(b, 1, 1, &fb, argb)) return 0;
  k = (div ? cspm_fdiv_tab : cspm_fmul_tab)[fa.s][fb.s];
  if (k >= 0) return cspm_fcreate(k, "0.0", 0, r);
  if (!cspm_fbasic(div ? 2 : 1, arga, argb, &s)) return 0;
  fa.e = cspm_w_add(fa.e, div ? -fb.e : fb.e);
  if (!cspm_fe(&s, fa.e, &q) || !cspm_fsplit(q.s, &fr)) return 0;
  return cspm_fcreate(-k, fr.m, fr.e, r);
}
static int cspm_frecip(const char *a, cspm_val *r) { return cspm_fmuldiv("1Y1.0e0]", a, r, 1); }

/* \pgfmathfloattofixed@ (finite numbers only: nan and inf are words). */
static int cspm_ftofixed(const char *a, cspm_val *r) {
  cspm_flt f; char out[CSPM_LEN * 2], i1[CSPM_LEN], i2[CSPM_LEN]; char *dot; int32_t E;
  if (!cspm_fsplit(a, &f)) return 0;
  if (f.s == 0) return cspm_set_val(r, "0.0");
  if (f.s > 2) return 0;
  dot = strchr(f.m, '.'); if (!dot) return 0;
  memcpy(i1, f.m, dot - f.m); i1[dot - f.m] = 0; strcpy(i2, dot + 1);   /* #1.#2 */
  E = f.e; out[0] = 0;
  if (f.s == 2) strcpy(out, "-");
  if (E < 0) {
    static const char *z[] = { "", "0.", "0.0", "0.00", "0.000", "0.0000", "0.00000", "0.000000", "0.0000000",
                               "0.00000000", "0.000000000" };
    if (-E <= 10) strcat(out, z[-E]);
    else {
      strcat(out, "0.0000000000");
      E += 10;
      while (E < -1) { if (strlen(out) + 2 >= sizeof out) return 0; strcat(out, "0"); E++; }
    }
    if (strlen(out) + strlen(i1) + strlen(i2) + 2 >= sizeof out) return 0;
    strcat(out, i1);
    if (strcmp(i2, "0")) strcat(out, i2);
  } else {
    char d[CSPM_LEN + 16]; size_t k;
    snprintf(d, sizeof d, "%s000000000", i2);                  /* #1..#8 one character each, #9 the rest */
    if (strlen(d) < 9) return 0;
    strcat(out, i1);
    if (E <= 8) {
      size_t L = strlen(out);
      memcpy(out + L, d, E); out[L + E] = 0;
      strcat(out, "."); strcat(out, d + E);
    } else {
      size_t L = strlen(out); const char *rest;
      memcpy(out + L, d, 8); out[L + 8] = 0;
      E -= 8; rest = d + 8;                                    /* \pgfmathfloattofixed@impl@collectmantissa */
      for (;;) {
        L = strlen(out); if (L + 3 >= sizeof out) return 0;
        out[L] = *rest; out[L + 1] = 0; rest++; E--;
        if (!*rest) {
          while (E > 0) { L = strlen(out); if (L + 3 >= sizeof out) return 0; strcat(out, "0"); E--; }
          strcat(out, ".0"); break;
        }
        if (E == 0) { if (strlen(out) + strlen(rest) + 2 >= sizeof out) return 0; strcat(out, "."); strcat(out, rest); break; }
      }
    }
    (void)k;
  }
  return cspm_set_val(r, out);
}
static int cspm_ftoint(const char *a, int32_t *v) {             /* \pgfmathfloattoint, then \count=<it> */
  cspm_val t; char *dot; const char *rest;
  if (!cspm_ftofixed(a, &t)) return 0;
  dot = strchr(t.s, '.'); if (!dot) return 0;
  *dot = 0;
  return cspm_scan_int_prefix(t.s, v, &rest) && !*rest;
}
static int cspm_fmod(const char *a, const char *b, cspm_val *r) {   /* \pgfmathfloatmod@ */
  int32_t ca, cb; char t[24]; cspm_val q, p;
  if (!cspm_ftoint(a, &ca) || !cspm_ftoint(b, &cb)) return 0;
  cspm_arith = 0; ca = cspm_x_over_n(ca, cb); if (cspm_arith) return 0;
  snprintf(t, sizeof t, "%d", ca);
  if (!cspm_fparse(t, &q) || !cspm_fmuldiv(q.s, b, &p, 0)) return 0;
  return cspm_fsub(a, p.s, r);
}
static int cspm_ftrig(const char *a, cspm_val *r, int which) {   /* \pgfmathfloatTRIG@: sin 1, cos 0 */
  cspm_val m, t, s;
  if (!cspm_fmod(a, cspm_trig ? "1Y6.28318530717959e0]" : "1Y3.6e2]", &m) || !cspm_ftofixed(m.s, &t)) return 0;
  if (!cspm_f_cossin(&t, &s, which)) return 0;
  return cspm_fparse(s.s, r);
}
static int cspm_ftan(const char *a, cspm_val *r) {
  cspm_val c, s;
  if (!cspm_ftrig(a, &c, 0) || !cspm_ftrig(a, &s, 1)) return 0;
  return cspm_fmuldiv(s.s, c.s, r, 1);
}
static int cspm_fexp(const char *a, cspm_val *r) {
  cspm_flt f; cspm_val t, e1, g; int32_t xa, k, cb, y; char loc[40], i1[24]; const char *dot, *rest;
  if (!cspm_fsplit(a, &f)) return 0;
  if (f.s == 0) return cspm_fcreate(1, "1.0", 0, r);
  if (f.s > 2) return cspm_set_val(r, a);
  if (!cspm_ftofixed(a, &t) || !cspm_scan_pt(t.s, &xa) || !cspm_scan_factor_dimen("0.434294481", xa, &xa)) return 0;
  cspm_print_scaled(xa, loc);                                   /* \pgfmathfloatexp@@toint */
  dot = strchr(loc, '.');
  memcpy(i1, loc, dot - loc); i1[dot - loc] = 0;
  if (!cspm_scan_int_prefix(i1, &k, &rest) || *rest) return 0;
  if (k < 0) {
    k = cspm_w_add(k, -1);
    if (!cspm_scan_int_prefix(dot + 1, &cb, &rest) || *rest) return 0;
    if (cb > 0) k = cspm_w_add(k, -1);
  }
  if (!cspm_scan_pt("2.302585092", &xa)) return 0;
  cspm_arith = 0; xa = cspm_nx_plus_y(xa, -k, 0); if (cspm_arith) return 0;
  if (!cspm_scan_pt(t.s, &y)) return 0;
  xa = cspm_w_add(xa, y);
  cspm_print_scaled(xa, loc);
  if (!cspm_set_val(&g, loc) || !cspm_f_exp(&g, &e1) || !cspm_fparse(e1.s, &g) || !cspm_fsplit(g.s, &f)) return 0;
  return cspm_fcreate(f.s, f.m, cspm_w_add(f.e, k), r);       /* \pgfmathfloatshift@ */
}
static int cspm_fpow(const char *a, const char *b, cspm_val *r) {
  cspm_flt f; cspm_val t, la, lb, n; int32_t ca, x; const char *rest; char tp[CSPM_LEN + 4];
  if (!cspm_fsplit(b, &f)) return 0;
  switch (f.s) {
    case 0: return cspm_fcreate(1, "1.0", 0, r);
    case 3: case 4: return cspm_set_val(r, b);
    case 5: return cspm_fcreate(0, "0.0", 0, r);
  }
  if (!cspm_ftofixed(b, &t)) return 0;
  if (!cspm_scan_int_prefix(t.s, &ca, &rest)) return 0;        /* \c@pgfmath@counta<t>pt, the rest into \pgfmath@x */
  snprintf(tp, sizeof tp, "%s", rest);
  if (!cspm_scan_pt(tp, &x)) return 0;
  if (x != 0) {                                                  /* ln and exp (pgfmath's code), unless a is 0 */
    cspm_flt g;
    if (!cspm_fsplit(a, &g) || g.s != 0) return 0;
    return cspm_fcreate(0, "0.0", 0, r);
  }
  if (ca < 0) { if (!cspm_frecip(a, &la)) return 0; ca = -ca; }
  else if (!cspm_set_val(&la, a)) return 0;
  if (!cspm_set_val(&lb, "1Y1.0e0]")) return 0;
  while (ca > 0) {
    if (ca & 1) { if (!cspm_fmuldiv(lb.s, la.s, &n, 0)) return 0; lb = n; }
    if (ca > 1) { if (!cspm_fmuldiv(la.s, la.s, &n, 0)) return 0; la = n; }
    ca /= 2;
  }
  *r = lb;
  return 1;
}

/* \pgfmathfloatln@ (\pgfmathlog@float): ln of the mantissa, plus the exponent times 2.302585; nan unless positive. */
static int cspm_fln(const char *a, cspm_val *r) {
  cspm_flt f; cspm_val m, l; int32_t bm, am; char t[40];
  if (!cspm_fsplit(a, &f)) return 0;
  if (f.s != 1) return cspm_fcreate(3, "0.0", 0, r);
  if (!cspm_set_val(&m, f.m) || !cspm_f_ln(&m, &l) || !cspm_scan_pt(l.s, &bm)) return 0;
  am = cspm_dim("2.302585");
  cspm_arith = 0; am = cspm_nx_plus_y(am, f.e, 0); if (cspm_arith) return 0;
  bm = cspm_w_add(bm, am);
  cspm_print_scaled(bm, t);
  return cspm_fparse(t, r);
}
static int cspm_flogk(const char *a, cspm_val *r, const char *constant) {   /* log10, log2: a constant times ln */
  cspm_val l;
  if (!cspm_fln(a, &l)) return 0;
  return cspm_fmuldiv(constant, l.s, r, 0);
}
/* \pgfmathfloatsqrt@: the basic sqrt of the mantissa (extended by three digits), times sqrt 10 or sqrt 0.1 for an odd
   exponent, which is then halved. */
static int cspm_fsqrt(const char *a, cspm_val *r) {
  cspm_flt f; char arg[CSPM_LEN + 16]; cspm_val m, q, t;
  if (!cspm_fext(a, 3, 0, &f, arg)) return 0;
  switch (f.s) {
    case 0: return cspm_fcreate(0, "0.0", 0, r);
    case 2: case 3: case 5: return cspm_fcreate(3, "0.0", 0, r);
    case 4: return cspm_fcreate(4, "0.0", 0, r);
  }
  if (!cspm_set_val(&m, arg) || !cspm_f_sqrt(&m, &q)) return 0;
  if (f.e & 1) {
    if (!cspm_set_val(&t, f.e > 0 ? "3.16227766" : "0.316227766") || !cspm_f_mul(&q, &t, &m)) return 0;
    q = m;
  }
  return cspm_fe(&q, cspm_x_over_n(f.e, 2), r);
}
/* The fpu operations pgfplots calls directly, on texts: parse (\pgfmathfloatparsenumber), add, sub, mul, div,
   tofixed, neg, abs, ln, sqrt; two arguments are separated by a comma. */
static int cspm_fop(const char *op, const char *args, char *out, int outsize) {
  char a[CSPM_LEN], b[CSPM_LEN]; const char *comma = strchr(args, ','); cspm_val r; int ok = 0, two;
  if (strlen(args) >= CSPM_LEN) return 0;
  cspm_fail = 0;
  if (comma) {
    memcpy(a, args, comma - args); a[comma - args] = 0; strcpy(b, comma + 1);
    if (strchr(b, ',')) return 0;
  } else { strcpy(a, args); b[0] = 0; }
  two = !strcmp(op, "add") || !strcmp(op, "sub") || !strcmp(op, "mul") || !strcmp(op, "div");
  if (two != (comma != NULL)) return 0;
  if (!strcmp(op, "parse")) ok = cspm_fparse(a, &r);
  else if (!strcmp(op, "add")) ok = cspm_fadd(a, b, &r);
  else if (!strcmp(op, "sub")) ok = cspm_fsub(a, b, &r);
  else if (!strcmp(op, "mul")) ok = cspm_fmuldiv(a, b, &r, 0);
  else if (!strcmp(op, "div")) ok = cspm_fmuldiv(a, b, &r, 1);
  else if (!strcmp(op, "tofixed")) ok = cspm_ftofixed(a, &r);
  else if (!strcmp(op, "neg")) ok = cspm_fneg(a, &r);
  else if (!strcmp(op, "abs")) ok = cspm_fabs(a, &r);
  else if (!strcmp(op, "ln")) ok = cspm_fln(a, &r);
  else if (!strcmp(op, "sqrt")) ok = cspm_fsqrt(a, &r);
  if (!ok || (int)strlen(r.s) + 1 > outsize) return 0;
  strcpy(out, r.s);
  return 1;
}

/* ---- the parser ---- */
enum { OP_NEG, OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_POW, OP_LPAREN, OP_R,
       OP_SIN, OP_COS, OP_TAN, OP_DEG, OP_RAD, OP_ABS, OP_EXP, OP_LN, OP_LOG10, OP_LOG2, OP_SQRT };
static const int cspm_op_prec[] = { 500, 500, 500, 700, 700, 900, 5, 600, 1000, 1000, 1000, 1000, 1000, 1000, 1000,
                                    1000, 1000, 1000, 1000 };
#define CSPM_NFN 11
static const char *const cspm_fn_names[CSPM_NFN] = { "sin", "cos", "tan", "deg", "rad", "abs", "exp", "ln", "log10", "log2", "sqrt" };

typedef struct {
  const cspm_tok *t; int n, i;
  int ops[CSPM_STACK], nops;
  cspm_val vals[CSPM_STACK]; int nvals;
  int units, fpu;
  const char *bind;          /* fpu: values of zero-argument functions, "name=value;name=value" */
} cspm_state;

static const cspm_tok cspm_end = { -1, '@', 11, 0 };
static const cspm_tok *cspm_rd_raw(cspm_state *s) {       /* the next token, spaces too; after the end, "@" */
  if (s->i < s->n) {
    const cspm_tok *k = &s->t[s->i++];
    if (k->kind == CSPM_CHAR && (k->cat == 1 || k->cat == 2)) { cspm_fail = 1; return &cspm_end; }
    return k;
  }
  return &cspm_end;
}
static const cspm_tok *cspm_rd(cspm_state *s) {           /* the next token, spaces skipped; after the end, "@" */
  while (s->i < s->n) {
    const cspm_tok *k = &s->t[s->i++];
    if (k->kind == CSPM_CHAR && k->cat == 10) continue;
    if (k->kind == CSPM_CHAR && (k->cat == 1 || k->cat == 2)) { cspm_fail = 1; return &cspm_end; }
    return k;
  }
  return &cspm_end;
}
static int cspm_is_end(const cspm_tok *k) { return k->kind == -1; }
static int cspm_is_ch(const cspm_tok *k, int c) { return k->kind == CSPM_CHAR && k->cat == 12 && k->ch == c; }
static int cspm_is_digit(const cspm_tok *k) { return k->kind == CSPM_CHAR && k->cat == 12 && k->ch >= '0' && k->ch <= '9'; }
static int cspm_is_letter(const cspm_tok *k) {
  return k->kind == CSPM_CHAR && (k->cat == 11 || k->cat == 12) &&
         ((k->ch >= 'a' && k->ch <= 'z') || (k->ch >= 'A' && k->ch <= 'Z'));
}

static int cspm_push_val(cspm_state *s, const char *v) {   /* fpu: \pgfmathfloat@stack@push@operand makes it a float */
  if (s->nvals >= CSPM_STACK) return 0;
  if (s->fpu && !strchr(v, 'Y')) return cspm_fparse(v, &s->vals[s->nvals++]);
  return cspm_set_val(&s->vals[s->nvals++], v);
}
static int cspm_apply(cspm_state *s, int op) {
  cspm_val r, a, b;
  if (op == OP_NEG || op == OP_LPAREN || op >= OP_R) {
    int ok = 1;
    if (s->nvals < 1) return 0;
    a = s->vals[--s->nvals];
    if (s->fpu) switch (op) {
      case OP_NEG: ok = cspm_fneg(a.s, &r); break;
      case OP_LPAREN: r = a; break;
      case OP_SIN: ok = cspm_ftrig(a.s, &r, 1); break;
      case OP_COS: ok = cspm_ftrig(a.s, &r, 0); break;
      case OP_TAN: ok = cspm_ftan(a.s, &r); break;
      case OP_R: case OP_DEG: ok = cspm_fmuldiv(a.s, "1Y5.72957795130823e1]", &r, 0); break;
      case OP_RAD: ok = cspm_fmuldiv(a.s, "1Y1.74532925199433e-2]", &r, 0); break;
      case OP_ABS: ok = cspm_fabs(a.s, &r); break;
      case OP_EXP: ok = cspm_fexp(a.s, &r); break;
      case OP_LN: ok = cspm_fln(a.s, &r); break;
      case OP_LOG10: ok = cspm_flogk(a.s, &r, "1Y4.34294481903252e-1]"); break;
      case OP_LOG2: ok = cspm_flogk(a.s, &r, "1Y1.44269504088896e0]"); break;
      case OP_SQRT: ok = cspm_fsqrt(a.s, &r); break;
    } else switch (op) {
      case OP_NEG: ok = cspm_f_neg(&a, &r); break;
      case OP_LPAREN: r = a; break;                    /* @startgroup: the operand itself */
      case OP_SIN: ok = cspm_f_cossin(&a, &r, 1); break;
      case OP_COS: ok = cspm_f_cossin(&a, &r, 0); break;
      case OP_TAN: ok = cspm_f_tan(&a, &r); break;
      case OP_R: case OP_DEG: ok = cspm_f_scale(&a, &r, "57.29577", 0); break;
      case OP_RAD: ok = cspm_f_scale(&a, &r, "3.14159", 180); break;
      case OP_ABS: ok = cspm_f_abs(&a, &r); break;
      case OP_EXP: ok = cspm_f_exp(&a, &r); break;
      case OP_LN: ok = cspm_f_ln(&a, &r); break;
      case OP_LOG10: ok = cspm_f_logk(&a, &r, "0.43429441"); break;
      case OP_LOG2: ok = cspm_f_logk(&a, &r, "1.442695041"); break;
      case OP_SQRT: ok = cspm_f_sqrt(&a, &r); break;
    }
    if (!ok) return 0;
  } else {
    int ok;
    if (s->nvals < 2) return 0;
    a = s->vals[--s->nvals]; b = s->vals[--s->nvals];  /* b op a */
    if (s->fpu) switch (op) {
      case OP_ADD: ok = cspm_fadd(b.s, a.s, &r); break;
      case OP_SUB: ok = cspm_fsub(b.s, a.s, &r); break;
      case OP_MUL: ok = cspm_fmuldiv(b.s, a.s, &r, 0); break;
      case OP_DIV: ok = cspm_fmuldiv(b.s, a.s, &r, 1); break;
      default: ok = cspm_fpow(b.s, a.s, &r); break;
    } else switch (op) {
      case OP_ADD: ok = cspm_f_add(&b, &a, &r, 0); break;
      case OP_SUB: ok = cspm_f_add(&b, &a, &r, 1); break;
      case OP_MUL: ok = cspm_f_mul(&b, &a, &r); break;
      case OP_DIV: ok = cspm_f_div(&b, &a, &r); break;
      default: ok = cspm_f_pow(&b, &a, &r); break;
    }
    if (!ok) return 0;
  }
  s->vals[s->nvals++] = r;
  return 1;
}
/* pgfmath's \pgfmath@operation@@cspm_process for an incoming operator of precedence p. */
static int cspm_process(cspm_state *s, int p, int rparen) {
  while (s->nops > 0) {
    int top = s->ops[s->nops - 1];
    if (p > cspm_op_prec[top]) break;
    s->nops--;
    if (!cspm_apply(s, top)) return 0;
    if (rparen && top == OP_LPAREN) return 1;
  }
  return !rparen;                                      /* a ) without its ( */
}

static int cspm_eval(const cspm_tok *toks, int n, int has_nd, int trig, int fpu, const char *bind, char *out, int outsize) {
  cspm_state st, *s = &st; const cspm_tok *tok, *next; int i, depth;
  cspm_fail = 0; cspm_nd = has_nd; cspm_trig = trig;
  if (fpu) {                                           /* \pgfmathparse@trynumber@loop: only 0-9 and . is a number */
    char b[CSPM_LEN]; cspm_val r;
    for (i = 0; i < n && i < CSPM_LEN - 1; i++) {
      if (toks[i].kind != CSPM_CHAR || toks[i].cat == 10 || toks[i].cat == 1 || toks[i].cat == 2) break;
      if (!((toks[i].ch >= '0' && toks[i].ch <= '9') || toks[i].ch == '.')) break;
      b[i] = (char)toks[i].ch;
    }
    if (n > 0 && i == n) {
      b[n] = 0;
      if (!cspm_fparse(b, &r) || (int)strlen(r.s) + 2 > outsize) return 0;
      out[0] = 'N'; strcpy(out + 1, r.s);
      return 1;
    }
  }
  /* pgfmath's \pgfmath@bgroup@strip: braces around the whole expression go */
  for (;;) {
    if (n >= 2 && toks[0].kind == CSPM_CHAR && toks[0].cat == 1) {
      depth = 0;
      for (i = 0; i < n; i++) {
        if (toks[i].kind == CSPM_CHAR && toks[i].cat == 1) depth++;
        if (toks[i].kind == CSPM_CHAR && toks[i].cat == 2 && --depth == 0) break;
      }
      if (i == n - 1) { toks++; n -= 2; continue; }
    }
    break;
  }
  s->t = toks; s->n = n; s->i = 0; s->nops = 0; s->nvals = 0; s->units = 0; s->fpu = fpu; s->bind = bind;
  tok = cspm_rd(s);
  for (;;) {                                           /* an operand */
    if (cspm_fail) return 0;
    if (cspm_is_end(tok)) return 0;
    if (cspm_is_ch(tok, '+')) { tok = cspm_rd(s); continue; }
    if (cspm_is_ch(tok, '-') || cspm_is_ch(tok, '(')) {
      if (s->nops >= CSPM_STACK) return 0;
      s->ops[s->nops++] = cspm_is_ch(tok, '-') ? OP_NEG : OP_LPAREN;
      tok = cspm_rd(s); continue;
    }
    if (cspm_is_letter(tok)) {                         /* \pgfmath@parse@function: a name, ended by a space or */
      char name[16]; int nn = 0, f; const cspm_tok *k;  /* anything but a letter, digit or _                   */
      name[nn++] = (char)tok->ch;
      for (;;) {
        k = cspm_rd_raw(s);
        if (cspm_fail) return 0;
        if (k->kind == CSPM_CHAR && k->cat != 10 && (cspm_is_letter(k) || (k->ch >= '0' && k->ch <= '9') || k->ch == '_')) {
          if (nn >= 15) return 0;
          name[nn++] = (char)k->ch; continue;
        }
        break;
      }
      name[nn] = 0;
      if (k->kind == CSPM_CHAR && k->cat == 10) k = cspm_rd(s);   /* (the space itself is skipped by what reads next) */
      {                                                /* no arguments: the value, then an operator */
        const char *v = NULL; char bv[CSPM_LEN];
        if (!strcmp(name, "pi")) v = "3.141592654";    /* (the fpu replaces \pgfmathe@ but not \pgfmathpi@) */
        else if (!strcmp(name, "e")) v = fpu ? "1Y2.71828182845905e0]" : "2.718281828";
        else if (fpu && bind) {                        /* pgfplots' x and y */
          size_t L = strlen(name); const char *q = bind;
          while (*q) {
            const char *semi = strchr(q, ';'), *end = semi ? semi : q + strlen(q);
            if ((size_t)(end - q) > L + 1 && !strncmp(q, name, L) && q[L] == '=' && (size_t)(end - q - L - 1) < CSPM_LEN) {
              memcpy(bv, q + L + 1, end - q - L - 1); bv[end - q - L - 1] = 0; v = bv; break;
            }
            if (!semi) break;
            q = semi + 1;
          }
        }
        if (v) {
          if (!cspm_push_val(s, v)) return 0;
          tok = k; next = cspm_rd(s);
          goto operator;
        }
      }
      for (f = 0; f < CSPM_NFN; f++) if (!strcmp(name, cspm_fn_names[f])) break;
      if (f == CSPM_NFN || s->nops >= CSPM_STACK) return 0;
      s->ops[s->nops++] = OP_SIN + f;
      tok = k; continue;
    }
    {
      char num[CSPM_LEN]; int nl = 0, base8, periods = 0; const cspm_tok *k;
      if (!(cspm_is_digit(tok) || cspm_is_ch(tok, '.') || tok->kind == CSPM_DIMEN || tok->kind == CSPM_COUNT)) return 0;
      base8 = cspm_is_ch(tok, '0');
      num[0] = 0;
      next = cspm_rd(s);
      for (;;) {                                       /* \pgfmath@parse@@number: tok, with next ahead */
        if (cspm_fail) return 0;
        if (tok->kind == CSPM_DIMEN) {
          char b[40]; int32_t v;
          if (periods > 1 || !cspm_scan_factor_dimen(num, tok->val, &v)) return 0;
          s->units = 1; cspm_print_scaled(v, b);
          if (!cspm_push_val(s, b)) return 0;
          tok = next; next = cspm_rd(s);                    /* \pgfmath@parse@operator */
          break;
        }
        if (tok->kind == CSPM_COUNT) {
          char b[24];
          if (nl || next->kind == CSPM_DIMEN || next->kind == CSPM_COUNT || next->kind == CSPM_OTHER) return 0;
          snprintf(b, sizeof b, "%d", tok->val);
          if (!cspm_push_val(s, b)) return 0;
          tok = next; next = cspm_rd(s);
          break;
        }
        if (tok->kind == CSPM_OTHER) return 0;
        if (cspm_is_digit(tok) || cspm_is_ch(tok, '.')) {
          if (nl + 1 >= CSPM_LEN) return 0;
          num[nl++] = (char)tok->ch; num[nl] = 0;
          if (tok->ch == '.') { base8 = 0; periods++; }
          tok = next; next = cspm_rd(s);
          continue;
        }
        if (tok->kind == CSPM_CHAR && tok->cat != 12 && tok->cat != 11 && tok->cat != 7 && tok->cat != 8) return 0;
        if (cspm_is_letter(tok) && cspm_is_letter(next)) {       /* a two-letter unit */
          char u[3] = { (char)tok->ch, (char)next->ch, 0 }; char b[40]; int32_t v;
          static const char *known = " bp cc cm dd em ex in mm pc pt sp nc nd px mu ";
          char probe[5] = { ' ', u[0], u[1], ' ', 0 };
          if (strstr(known, probe)) {
            if (periods > 1 || !cspm_scan_dimen_unit(num, u, &v)) return 0;   /* em, ex, px, mu: pgfmath's code */
            s->units = 1; cspm_print_scaled(v, b);
            if (!cspm_push_val(s, b)) return 0;
            tok = cspm_rd(s); next = cspm_rd(s);                 /* \pgfmath@parse@@operator */
            break;
          }
        }
        if (fpu && tok->kind == CSPM_CHAR && tok->ch == 'Y') {  /* \pgfmathfloat@return@float: a float written out */
          char b[CSPM_LEN]; size_t L;
          if (!strlen(num) || strchr(num, '.') || !cspm_append(strcpy(b, num), "Y")) return 0;
          for (k = next; ; k = cspm_rd_raw(s)) {
            char c2[2] = { 0, 0 };
            if (cspm_fail || cspm_is_end(k) || k->kind != CSPM_CHAR || k->cat == 10) return 0;
            c2[0] = (char)k->ch;
            if (!cspm_append(b, c2)) return 0;
            if (k->ch == ']') break;
          }
          L = strlen(b); (void)L;
          if (s->nvals >= CSPM_STACK || !cspm_set_val(&s->vals[s->nvals++], b)) return 0;   /* (pushed as it is) */
          tok = cspm_rd(s); next = cspm_rd(s);         /* \pgfmath@parse@@operator */
          break;
        }
        if (fpu && tok->kind == CSPM_CHAR && (tok->ch == 'e' || tok->ch == 'E')) {   /* \pgfmathfloatscientific */
          char b[CSPM_LEN + 24]; int32_t v = 0; int neg = 0, digits = 0;
          k = next;                                    /* \pgfmath@count<next>...: signs, then digits */
          while (k->kind == CSPM_CHAR && (k->cat == 10 || cspm_is_ch(k, '+') || cspm_is_ch(k, '-'))) {
            if (cspm_is_ch(k, '-')) neg = !neg;
            k = cspm_rd_raw(s);
          }
          while (cspm_is_digit(k)) {
            int d = k->ch - '0';
            if (v >= 214748364 && (v > 214748364 || d > 7)) return 0;
            v = v * 10 + d; digits++;
            k = cspm_rd_raw(s);
          }
          if (cspm_fail || !digits || periods > 1) return 0;
          if (k->kind == CSPM_CHAR && k->cat == 10) k = cspm_rd(s);   /* (one space ends the number) */
          snprintf(b, sizeof b, "%se%d", num, neg ? -v : v);
          if (s->nvals >= CSPM_STACK || !cspm_fparse(b, &s->vals[s->nvals++])) return 0;
          tok = k; next = cspm_rd(s);                  /* \pgfmath@parse@@operator */
          break;
        }
        if (tok->ch == 'e' || tok->ch == 'E') return 0;                          /* scientific */
        if (!strcmp(num, "0") && strchr("xXbB", tok->ch) && tok->kind == CSPM_CHAR) return 0;   /* 0x, 0b */
        if (base8 && strcmp(num, "0")) return 0;                                 /* octal */
        if (!cspm_push_val(s, num)) return 0;               /* the number as written */
        break;                                         /* \pgfmath@parse@@@operator: tok is the operator */
      }
    }
    operator:
    for (;;) {                                         /* an operator: tok, next */
      if (cspm_fail) return 0;
      if (cspm_is_end(tok)) {
        for (i = 0; i < s->nops; i++) if (s->ops[i] == OP_LPAREN) return 0;   /* a ( never closed */
        if (!cspm_process(s, 0, 0) || s->nvals != 1) return 0;
        if ((int)strlen(s->vals[0].s) + 2 > outsize) return 0;
        out[0] = s->units ? 'U' : 'N'; strcpy(out + 1, s->vals[0].s);
        return 1;
      }
      if (tok->kind == CSPM_CHAR && tok->ch == 'r' && (tok->cat == 11 || tok->cat == 12)) {   /* postfix r: deg */
        if (!cspm_process(s, 600, 0) || s->nops >= CSPM_STACK) return 0;
        s->ops[s->nops++] = OP_R;
        tok = next; next = cspm_rd(s);
        continue;
      }
      /* (pgfmath finds an operator by its name, whatever the catcode: ^ is usually a superscript character) */
      if (tok->kind != CSPM_CHAR || (tok->cat != 12 && tok->cat != 7 && tok->cat != 8 && tok->cat != 11)) return 0;
      if ((tok->ch == '=' || tok->ch == '>' || tok->ch == '<' || tok->ch == '!') && cspm_is_ch(next, '=')) return 0;
      if ((tok->ch == '&' && cspm_is_ch(next, '&')) || (tok->ch == '|' && cspm_is_ch(next, '|'))) return 0;
      if (tok->ch == ')') {
        if (!cspm_process(s, 4, 1)) return 0;
        tok = next; next = cspm_rd(s);
        continue;
      }
      {
        int op;
        switch (tok->ch) {
          case '+': op = OP_ADD; break;
          case '-': op = OP_SUB; break;
          case '*': op = OP_MUL; break;
          case '/': op = OP_DIV; break;
          case '^': op = OP_POW; break;
          default: return 0;
        }
        if (!cspm_process(s, cspm_op_prec[op], 0)) return 0;
        if (s->nops >= CSPM_STACK) return 0;
        s->ops[s->nops++] = op;
        tok = next;                                    /* \pgfmath@parse@operand: the token ahead */
        break;
      }
    }
  }
}

/* The engine's entry (\pdfstrcmp or \strcmp with a first argument starting "clearsnapnative"): pgfmath<trig format>
   parses plain pgfmath, fpu<trig format>[;name=value;...] parses with the fpu (zero-argument functions bound to
   values), fpuop:<operation> applies an fpu operation to the second argument's text. 0: pgfmath's code runs. */
static int cspm_run(const char *magic, const cspm_tok *toks, int n, int has_nd, char *out, int outsize) {
  const char *m = magic + 15;
  if (strncmp(magic, "clearsnapnative", 15)) return 0;
  if (!strncmp(m, "pgfmath", 7) && (m[7] == '0' || m[7] == '1') && !m[8])
    return cspm_eval(toks, n, has_nd, m[7] == '1', 0, NULL, out, outsize);
  if (!strncmp(m, "fpuop:", 6)) {
    char a[CSPM_LEN]; int i;
    if (n >= CSPM_LEN) return 0;
    for (i = 0; i < n; i++) {
      if (toks[i].kind != CSPM_CHAR || toks[i].cat == 10 || toks[i].cat == 1 || toks[i].cat == 2 || toks[i].ch > 126) return 0;
      a[i] = (char)toks[i].ch;
    }
    a[n] = 0;
    return cspm_fop(m + 6, a, out, outsize);
  }
  if (!strncmp(m, "fpu", 3) && (m[3] == '0' || m[3] == '1') && (!m[4] || m[4] == ';'))
    return cspm_eval(toks, n, has_nd, m[3] == '1', 1, m[4] ? m + 5 : NULL, out, outsize);
  return 0;
}

#ifdef CSPM_TEST
#include <stdio.h>
#include <stdlib.h>
/* test: reads "R name d|c value" lines (registers) and "E expression" lines, prints "<result or FALLBACK>" per E.
   In expressions, \name is a register; letters are catcode 11, other characters 12, space 10, braces 1 and 2. */
int main(int argc, char **argv) {
  char line[4096]; static char names[512][64]; static int kinds[512]; static int32_t vals[512]; int nr = 0;
  int nd = argc > 1 && !strcmp(argv[1], "nd"), trig = 0, fpu = 0; static char bind[2048];
  while (fgets(line, sizeof line, stdin)) {
    size_t L = strlen(line); while (L && (line[L - 1] == '\n' || line[L - 1] == '\r')) line[--L] = 0;
    if (line[0] == 'R') {
      char nm[64], k; long v;
      if (sscanf(line + 2, "%63s %c %ld", nm, &k, &v) == 3 && nr < 512) { strcpy(names[nr], nm); kinds[nr] = k == 'd' ? CSPM_DIMEN : CSPM_COUNT; vals[nr] = (int32_t)v; nr++; }
      continue;
    }
    if (line[0] == 'T') { trig = line[2] == '1'; continue; }
    if (line[0] == 'F') { fpu = line[2] == '1'; continue; }
    if (line[0] == 'B') { strncpy(bind, line + 2, sizeof bind - 1); continue; }
    if (line[0] == 'O') {                              /* O op arg[,arg]: an fpu operation on texts */
      char op[16], arg[2048], out[512];
      if (sscanf(line + 2, "%15s %2047s", op, arg) >= 1) { if (sscanf(line + 2, "%15s %2047s", op, arg) == 1) arg[0] = 0;
        if (cspm_fop(op, arg, out, sizeof out)) printf("%s\n", out); else printf("FALLBACK\n"); }
      continue;
    }
    if (line[0] != 'E') continue;
    {
      cspm_tok toks[1024]; int n = 0; const char *p = line + 2; char out[256];
      while (*p && n < 1024) {
        cspm_tok t = { CSPM_CHAR, 0, 12, 0 };
        if (*p == '\\') {
          char nm[64]; int k = 0, r; p++;
          while (((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || *p == '@') && k < 63) nm[k++] = *p++;
          nm[k] = 0;
          t.kind = CSPM_OTHER;
          for (r = 0; r < nr; r++) if (!strcmp(names[r], nm)) { t.kind = kinds[r]; t.val = vals[r]; }
          while (*p == ' ') p++;                       /* the space after a control word is not a token */
        } else {
          t.ch = (unsigned char)*p;
          if ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')) t.cat = 11;
          else if (*p == ' ') t.cat = 10;
          else if (*p == '{') t.cat = 1;
          else if (*p == '^') t.cat = 7;                 /* (as in a document) */
          else if (*p == '_') t.cat = 8;
          else if (*p == '}') t.cat = 2;
          p++;
        }
        toks[n++] = t;
      }
      if (cspm_eval(toks, n, nd, trig, fpu, bind[0] ? bind : NULL, out, sizeof out)) printf("%s\n", out); else printf("FALLBACK\n");
    }
  }
  return 0;
}
#endif
