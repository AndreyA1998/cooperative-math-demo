"""Native runtime and static WebKit harness; no generator HTTP backend."""
import atexit
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
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


def compile_webkit(directory):
    directory = Path(directory)
    source, runner = directory / "runner.m", directory / "runner"
    source.write_text(WEBKIT_RUNNER, encoding="utf-8")
    subprocess.run(
        ["clang", "-fobjc-arc", str(source), "-framework", "WebKit",
         "-framework", "Foundation", "-o", str(runner)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return runner


def run_webkit(runner, url, script, *, timeout=240):
    script_path = Path(runner).parent / "case.js"
    script_path.write_text(JS_HELPERS + script, encoding="utf-8")
    result = subprocess.run([str(runner), url, str(script_path)],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        diagnostic = result.stdout + result.stderr
        print(diagnostic, file=sys.stderr, flush=True)
        raise AssertionError(diagnostic)
    return result.stdout
