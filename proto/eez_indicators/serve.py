"""serve proto/eez_indicators on localhost only, with HTTP Range (PMTiles reads byte ranges)."""
from __future__ import annotations

import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


class RangeHandler(SimpleHTTPRequestHandler):
  def send_head(self):
    m = re.match(r"bytes=(\d+)-(\d*)$", self.headers.get("Range", ""))
    path = Path(self.translate_path(self.path))
    if not m or not path.is_file():
      return super().send_head()
    size = path.stat().st_size
    start, end = int(m.group(1)), int(m.group(2) or size - 1)
    end = min(end, size - 1)
    f = open(path, "rb")
    f.seek(start)
    self.send_response(206)
    self.send_header("Content-Type", self.guess_type(str(path)))
    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    self.send_header("Content-Length", str(end - start + 1))
    self.send_header("Accept-Ranges", "bytes")
    self.end_headers()
    self._remaining = end - start + 1
    return f

  def copyfile(self, source, outputfile):
    n = getattr(self, "_remaining", None)
    if n is None:
      return super().copyfile(source, outputfile)
    outputfile.write(source.read(n))


if __name__ == "__main__":
  port = int(sys.argv[1]) if len(sys.argv) > 1 else 5190
  os.chdir(HERE)
  print(f"http://localhost:{port}/")
  ThreadingHTTPServer(("127.0.0.1", port), partial(RangeHandler, directory=str(HERE))).serve_forever()
