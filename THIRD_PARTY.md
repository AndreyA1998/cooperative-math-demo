# Third-party components

- The bundled corpus is derived from **MATH**, Dan Hendrycks et al., distributed under the MIT license. The original notice is included as `data/LICENSE.MATH` in `runtime.zip`; `data/source.lock.json` records the source revision and patched input provenance.
- **Pyodide 314.0.7** supplies CPython/WebAssembly in a module Web Worker. It is loaded from the versioned jsDelivr URL. Pyodide is MPL-2.0; CPython and the bundled runtime components retain their own licenses: <https://github.com/pyodide/pyodide/blob/main/LICENSE>.
- **KaTeX 0.19.1** renders mathematical notation under the MIT license, loaded from jsDelivr with Subresource Integrity: <https://github.com/KaTeX/KaTeX/blob/main/LICENSE>.

No model inference service or analytics is used. The initial page load fetches static assets from GitHub Pages and these versioned CDN distributions. Task generation itself executes locally in the visitor's browser.
