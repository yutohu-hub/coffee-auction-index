"""プレビュー用の静的サーバ。

プレビュープロセスの起動時 cwd がサンドボックスで参照不能なことがあり、
`python -m http.server`（起動時に os.getcwd() を呼ぶ）が失敗する。
そこで最初に docs へ os.chdir し、明示的な directory= で配信して getcwd を避ける。
ポートは環境変数 PORT（autoPort）→ argv[1] → 既定 8811 の順で決定。
"""
import functools
import http.server
import os
import socketserver
import sys

DOCS = "/Users/suzukiyuto/Downloads/coffee-auction-tracker/docs"

try:
    os.chdir(DOCS)  # chdir(2) は getcwd を必要としないため壊れた cwd でも成功する
except OSError:
    pass

port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8811))
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DOCS)
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
    print(f"serving {DOCS} on http://127.0.0.1:{port}")
    httpd.serve_forever()
