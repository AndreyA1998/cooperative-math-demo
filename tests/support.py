"""Native runtime and static browser harness; no generator HTTP backend."""
import atexit
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MOUNT = "/cooperative-math-demo/"
HAS_WEBKIT = sys.platform == "darwin" and shutil.which("clang") is not None
HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
HAS_BROWSER = HAS_WEBKIT or HAS_PLAYWRIGHT
BROWSER_REQUIREMENT = "Requires Playwright with Chromium, or native macOS WebKit and Clang"
if os.environ.get("MATH_DEMO_REQUIRE_BROWSER") == "1" and not HAS_BROWSER:
    raise RuntimeError("Browser checks are required: install requirements-test.txt and run playwright install --only-shell chromium")


def ensure_runtime():
    """Use an explicit source checkout or unpack the published runtime once."""
    packages = ("source_dataset", "template_dataset", "composite_dataset")
    if any(importlib.util.find_spec(name) is None for name in packages):
        temporary = tempfile.TemporaryDirectory(prefix="math-demo-native-")
        atexit.register(temporary.cleanup)
        with zipfile.ZipFile(ROOT / "runtime.zip") as archive:
            archive.extractall(temporary.name)
        sys.path.insert(0, temporary.name)
    # An explicit runtime (including scripts/check.py) owns the dataset packages
    # and math_demo. A source checkout needs the current public bridge fallback.
    if importlib.util.find_spec("math_demo") is None:
        sys.path.insert(0, str(ROOT / "python"))


def large_integer_schema(schema):
    """Equivalent saved program with coefficients outside JavaScript's safe range."""
    from copy import deepcopy
    from composite_dataset import render
    from composite_dataset.schema import _expected_bindings, schema_id
    result = deepcopy(schema)
    result.pop('problem_template')
    for node in result['nodes']:
        for name in ('numerator', 'denominator', 'divisor'):
            node['profile']['classifier'][name] *= 2**100 + 1
    by_id = {node['node_id']: node for node in result['nodes']}
    for node in result['nodes']:
        node['bindings'] = _expected_bindings(node, by_id)
    result['schema_id'] = schema_id(result)
    result['problem_template'] = render(result)
    return result


WEBKIT_RUNNER = r'''
#import <WebKit/WebKit.h>

@interface Runner : NSObject <WKNavigationDelegate>
@property NSString *script;
@property BOOL started;
@end

@implementation Runner
- (void)webView:(WKWebView *)view didFinishNavigation:(WKNavigation *)navigation {
    if (self.started) return;
    self.started = YES;
    [view callAsyncJavaScript:self.script arguments:@{} inFrame:nil
               inContentWorld:WKContentWorld.pageWorld completionHandler:^(id value, NSError *error) {
        if (error) fprintf(stderr, "%s\n", error.description.UTF8String);
        else if (value) printf("%s\n", [[value description] UTF8String]);
        exit(error ? 1 : 0);
    }];
}
- (void)webView:(WKWebView *)view didFailProvisionalNavigation:(WKNavigation *)navigation
      withError:(NSError *)error {
    fprintf(stderr, "%s\n", error.description.UTF8String);
    exit(1);
}
@end

int main(int argc, char **argv) {
    @autoreleasepool {
        Runner *runner = [Runner new];
        NSError *error = nil;
        runner.script = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]
                                                 encoding:NSUTF8StringEncoding error:&error];
        if (error) { fprintf(stderr, "%s\n", error.description.UTF8String); return 1; }
        WKWebViewConfiguration *config = [WKWebViewConfiguration new];
        config.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *view = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 1000)
                                           configuration:config];
        view.navigationDelegate = runner;
        [view loadRequest:[NSURLRequest requestWithURL:
            [NSURL URLWithString:[NSString stringWithUTF8String:argv[1]]]]];
        [NSRunLoop.mainRunLoop run];
    }
}
'''

PLAYWRIGHT_RUNNER = r'''
import asyncio
from pathlib import Path
import sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(sys.argv[1], wait_until="load", timeout=30000)
            source = Path(sys.argv[2]).read_text(encoding="utf-8")
            value = await asyncio.wait_for(
                page.evaluate("async () => {\n" + source + "\n}"),
                timeout=float(sys.argv[3]),
            )
            if value is not None:
                print(value, flush=True)
        except Exception:
            if errors:
                print("\n".join(errors[-5:]), file=sys.stderr)
            raise
        finally:
            await browser.close()

asyncio.run(main())
'''


JS_HELPERS = r'''
const $ = id => document.getElementById(id);
const check = (condition, message) => { if (!condition) throw new Error(message); };
const until = async (condition, message = "UI", options = {}) => {
  const deadline = Date.now() + (options.timeout || 150000);
  while (!condition() && Date.now() < deadline) {
    if (!options.allowError) {
      const error = [...document.querySelectorAll(".status.error:not([hidden]), #runtime-status.error")]
        .find(element => element.textContent);
      if (error) throw new Error(message + ": " + error.textContent);
    }
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  check(condition(), "Timed out: " + message + "; " + $("runtime-status").textContent);
};
const change = (id, value) => {
  $(id).value = value;
  $(id).dispatchEvent(new Event("change", {bubbles: true}));
};
const idleAtomic = () => !$("atomic-catalogue-controls").disabled && $("atomic-status").hidden;
const selectAtomic = async source => {
  await until(idleAtomic, "catalogue ready");
  const [subject, split] = source.split("/");
  if ($("atomic-subject").value !== subject) { change("atomic-subject", subject); await until(idleAtomic, "subject selected"); }
  if ($("atomic-split").value !== split) { change("atomic-split", split); await until(idleAtomic, "split selected"); }
  change("atomic-problem-id", source);
  await until(idleAtomic, "task selected explicitly");
};
const idleComposite = () => $("composite-status").hidden && !$("composite-structure-controls").disabled;
'''


class StaticHarness:
    """A repository-subpath origin serving files only, with optional failures."""

    def __init__(self, *, fail_once=()):
        self.requests = []
        self.fail_once = set(fail_once)
        self.lock = threading.Lock()
        harness = self

        class StaticHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                original = urlsplit(self.path).path
                with harness.lock:
                    harness.requests.append(("GET", original))
                    fail = original in harness.fail_once
                    harness.fail_once.discard(original)
                if original in (MOUNT + "__renderer_test__.html", MOUNT + "__component_test__.html"):
                    if original.endswith("__component_test__.html"):
                        html = (ROOT / "index.html").read_text(encoding="utf-8")
                        html = re.sub(r'<script[^>]+src="\./main\.js"[^>]*>\s*</script>', '', html)
                        content = html.encode("utf-8")
                    else:
                        content = b'<!doctype html><html><head><meta charset="utf-8"></head><body><p id="runtime-status"></p></body></html>'
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                if fail:
                    self.send_error(503, "Intentional first download failure")
                    return
                if not original.startswith(MOUNT):
                    self.send_error(404)
                    return
                self.path = self.path[len(MOUNT) - 1:]
                super().do_GET()

            def do_POST(self):
                with harness.lock:
                    harness.requests.append(("POST", self.path))
                self.send_error(404, "This origin has no API server")

            def log_message(self, *_args):
                pass

        handler = partial(StaticHandler, directory=str(ROOT))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}{MOUNT}"

    def close(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()


@contextmanager
def static_origin(**options):
    harness = StaticHarness(**options)
    try:
        yield harness
    finally:
        harness.close()


def prepare_browser(directory):
    directory = Path(directory)
    if not HAS_WEBKIT:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError(BROWSER_REQUIREMENT)
        runner = directory / "playwright_runner.py"
        runner.write_text(PLAYWRIGHT_RUNNER, encoding="utf-8")
        return runner
    source, runner = directory / "runner.m", directory / "runner"
    source.write_text(WEBKIT_RUNNER, encoding="utf-8")
    subprocess.run(
        ["clang", "-fobjc-arc", str(source), "-framework", "WebKit",
         "-framework", "Foundation", "-o", str(runner)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return runner


def run_browser(runner, url, script, *, timeout=240):
    script_path = Path(runner).parent / "case.js"
    script_path.write_text(JS_HELPERS + script, encoding="utf-8")
    env = dict(os.environ)
    if Path(runner).suffix == ".py":
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".cache/ms-playwright"))
        command = [sys.executable, "-B", str(runner), url, str(script_path), str(timeout)]
    else:
        command = [str(runner), url, str(script_path)]
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            timeout=timeout + 45)
    if result.returncode:
        diagnostic = result.stdout + result.stderr
        print(diagnostic, file=sys.stderr, flush=True)
        raise AssertionError(diagnostic)
    return result.stdout
