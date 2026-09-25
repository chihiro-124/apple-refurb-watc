"""
Apple 認定整備済製品（日本・Mac）の入荷を監視し、条件に合う新着を LINE に通知する。
"""
import json
import os
import re
import sys
import urllib.request

URL = "https://www.apple.com/jp/shop/refurbished/mac"
SEEN_FILE = "seen.json"

# ============ 条件設定（ここを編集） ============
INCLUDE_ALL = ["MacBook Air"]   # 商品名にすべて含まれている必要がある語
INCLUDE_ANY = ["M2", "M3", "M4", "M5"]  # いずれか1つ含まれていればOK（空リストなら条件なし）
EXCLUDE = []                    # 1つでも含まれていたら除外する語（例: ["15インチ"]）
MAX_PRICE = 200000              # 上限価格（円・税込）。条件なしなら None
MIN_MEMORY_GB = 16              # 最低メモリ（GB）。条件なしなら None
MIN_STORAGE_GB = 512            # 最低ストレージ（GB）。条件なしなら None
# ===============================================


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def extract_tiles(html):
    m = re.search(r"window\.REFURB_GRID_BOOTSTRAP\s*=\s*", html)
    if not m:
        raise RuntimeError("商品データが見つかりません。Apple のページ構造が変わった可能性があります。")
    data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    tiles = data.get("tiles") or []
    if not tiles:
        raise RuntimeError("商品リストが空です。ページ構造の変更かアクセス制限の可能性があります。")
    return tiles


def get_price(tile):
    cur = (tile.get("price") or {}).get("currentPrice") or {}
    raw = cur.get("raw_amount")
    if raw:
        return int(float(raw))
    digits = re.sub(r"[^\d]", "", (cur.get("amount") or "").split("(")[0])
    return int(digits) if digits else None


def get_memory_gb(title):
    m = re.search(r"(\d+)\s*GB\s*ユニファイドメモリ", title)
    return int(m.group(1)) if m else None


def get_storage_gb(title):
    m = re.search(r"(\d+)\s*(GB|TB)\s*SSD", title)
    if not m:
        return None
    return int(m.group(1)) * (1024 if m.group(2) == "TB" else 1)


def matches(title, price):
    if any(w not in title for w in INCLUDE_ALL):
        return False
    if INCLUDE_ANY and not any(w in title for w in INCLUDE_ANY):
        return False
    if any(w in title for w in EXCLUDE):
        return False
    if MAX_PRICE is not None and (price is None or price > MAX_PRICE):
        return False
    if MIN_MEMORY_GB is not None:
        mem = get_memory_gb(title)
        if mem is None or mem < MIN_MEMORY_GB:
            return False
    if MIN_STORAGE_GB is not None:
        sto = get_storage_gb(title)
        if sto is None or sto < MIN_STORAGE_GB:
            return False
    return True


def send_line(text):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]
    body = json.dumps({"to": user_id, "messages": [{"type": "text", "text": text[:4900]}]}).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def load_seen():
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def main():
    tiles = extract_tiles(fetch(URL))
    matched = {}
    for t in tiles:
        title = (t.get("title") or "").replace("\u00a0", " ")
        price = get_price(t)
        key = t.get("partNumber") or title
        if matches(title, price):
            link = t.get("productDetailsUrl") or ""
            if link.startswith("/"):
                link = "https://www.apple.com" + link
            matched[key] = {"title": title, "price": price, "url": link.split("?")[0]}

    seen = load_seen()
    new_items = [v for k, v in matched.items() if k not in seen]
    print(f"全{len(tiles)}件 / 条件一致{len(matched)}件 / 新着{len(new_items)}件")

    if new_items:
        lines = [f"🍎 整備済Mac 新着 {len(new_items)}件"]
        for it in new_items[:10]:
            price = f"¥{it['price']:,}" if it["price"] else "価格不明"
            lines.append(f"\n{it['title']}\n{price}\n{it['url']}")
        if len(new_items) > 10:
            lines.append(f"\nほか{len(new_items) - 10}件 → {URL}")
        text = "\n".join(lines)
        if os.environ.get("DRY_RUN"):
            print(text)
        else:
            send_line(text)

    # 現在在庫にある一致商品だけを記録（売り切れ→再入荷でも再通知される）
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(matched.keys()), f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

