// Lazy fonts (make-bundles-v5.py): the font bundles are mounted as markers, and a file TeX opens is fetched on its own
// from /v5/files right then, synchronously (allowed in a worker), so the run goes on instead of failing and
// downloading the whole bundle. Repeat fetches come from the browser's cache (the files are immutable), and the
// templates' files are already there: runner.js prefetches them while the engine loads.
const CLEARSNAP_FILES = '/v5/files';
function clearsnapFetchFile(path, length) {
    try {
        const xhr = new XMLHttpRequest();
        xhr.open('GET', CLEARSNAP_FILES + path, false);
        xhr.responseType = 'arraybuffer';
        xhr.send();
        if (xhr.status !== 200 || !xhr.response || xhr.response.byteLength !== length) return null;
        return new Uint8Array(xhr.response);
    } catch (e) {
        return null;
    }
}
