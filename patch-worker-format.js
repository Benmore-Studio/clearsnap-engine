// ============ Clearsnap: preamble formats and PDF objects ============
// pdfTeX can't keep PDF objects in a format: \dump discards them ("dangling objects discarded") while the macros that
// refer to them stay, and using one later crashes the engine (native pdfTeX segfaults the same way). PGF makes such
// objects as soon as a shading with fixed colors or a fading is declared, which libraries like fadings, shadows and
// tcolorbox's vignette do when they load. While a format is built, those declarations wait for \begin{document}: they
// are saved in the format and make their objects in each compile that uses it. A preamble that makes objects in
// another way (its own images, fadings drawn as pictures, raw objects) gets no format, and a format whose build still
// reports dangling objects is thrown away.
const FMT_MAKES_OBJECTS = /\\(tikzfading|pgfdeclareimage|pdfobj|pdfxform|pdfximage)\b/;

// Before the preamble: once PGF is loaded, shadings and fadings (unless drawn from a box) are declared at
// \begin{document}.
const FMT_OBJECTS_LATER = String.raw`\makeatletter
\def\clearsnap@ifbox#1{\clearsnap@ifbox@#1\box\clearsnap@nil}
\def\clearsnap@ifbox@#1\box#2\clearsnap@nil{\if\relax\detokenize{#2}\relax\expandafter\@secondoftwo\else\expandafter\@firstoftwo\fi}
\def\clearsnap@objectslater{%
  \let\clearsnap@horishading\pgfsys@horishading
  \def\pgfsys@horishading##1##2##3{\AtBeginDocument{\pgf@setup@shading@model\clearsnap@horishading{##1}{##2}{##3}}}%
  \let\clearsnap@vertshading\pgfsys@vertshading
  \def\pgfsys@vertshading##1##2##3{\AtBeginDocument{\pgf@setup@shading@model\clearsnap@vertshading{##1}{##2}{##3}}}%
  \let\clearsnap@radialshading\pgfsys@radialshading
  \def\pgfsys@radialshading##1##2##3{\AtBeginDocument{\pgf@setup@shading@model\clearsnap@radialshading{##1}{##2}{##3}}}%
  \let\clearsnap@functionalshading\pgfsys@functionalshading
  \def\pgfsys@functionalshading##1##2##3##4{\AtBeginDocument{\pgf@setup@shading@model\clearsnap@functionalshading{##1}{##2}{##3}{##4}}}%
  \let\clearsnap@declarefading\pgfdeclarefading
  \def\pgfdeclarefading##1##2{\clearsnap@ifbox{##2}{\clearsnap@declarefading{##1}{##2}}{\AtBeginDocument{\clearsnap@declarefading{##1}{##2}}}}}
\AddToHook{package/pgfcore/after}{\clearsnap@objectslater}
\makeatother`;

// After the preamble, before \dump: the format keeps PGF's own definitions for the document.
const FMT_OBJECTS_NOW = String.raw`\makeatletter
\ifdefined\clearsnap@declarefading
  \let\pgfsys@horishading\clearsnap@horishading
  \let\pgfsys@vertshading\clearsnap@vertshading
  \let\pgfsys@radialshading\clearsnap@radialshading
  \let\pgfsys@functionalshading\clearsnap@functionalshading
  \let\pgfdeclarefading\clearsnap@declarefading
\fi
\makeatother`;

// The text to build a preamble's format from, or null when it should get no format.
function formatSource(preamble) {
    if (FMT_MAKES_OBJECTS.test(preamble.replace(/(^|[^\\])%[^\n]*/g, '$1'))) return null;
    return FMT_OBJECTS_LATER + '\n' + preamble + '\n' + FMT_OBJECTS_NOW;
}

