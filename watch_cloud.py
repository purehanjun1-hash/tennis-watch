"""빈자리 감시 - 클라우드(GitHub Actions)용

GitHub이 30분마다 이 파일을 한 번 실행한다. 한 번 확인하고 끝난다.
- 감시할 날짜·시간·사이트: settings.json (GitHub 웹에서 고칠 수 있음)
- 이미 알린 빈자리: state.json (같은 자리는 다시 알리지 않음)
- 휴대폰 알림 주제: GitHub Secrets의 NTFY_TOPIC
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# ---- 스포원 ----
SP_URL = ("https://nrsv.spo1.or.kr/fmcs/42?facilities_type=T&base_date={ymd}"
          "&rent_type=1001&center=SPOONE&part={part}&place={place}")
SP_PART = {"실외": 15, "실내": 11}
SP_COURTS = {
    "실외": [("01번", 61), ("02번", 8), ("03번", 12), ("04번", 13), ("05번", 14), ("06번", 15),
             ("07번", 16), ("08번", 17), ("09번", 18), ("10번", 19), ("11번", 20),
             ("센터코트", 59), ("서브코트", 7)],
    "실내": [("1번", 21), ("2번", 22), ("3번", 23), ("4번", 24), ("5번", 25), ("6번", 26)],
}
JS_ROW = r"""
(tm) => {
  const norm = s => (s || '').replace(/\s+/g, '').replace(/[～∼]/g, '~');
  const row = [...document.querySelectorAll('tr')].find(t => norm(t.innerText).includes(norm(tm)));
  if (!row) return null;
  const cb = row.querySelector('input[type=checkbox]');
  return {text: row.innerText.replace(/\s+/g, ' ').replace(/^- /, '').trim(), open: !!(cb && !cb.disabled)};
}
"""

# ---- 수목원 ----
ARB_JSON = "https://reserve.busan.go.kr/comm/resve/json/getResveTimeRentHaeundae.json"
ARB_PAGE = "https://reserve.busan.go.kr/rent/preStep?resveProgrmSe=R&resveGroupSn=531&progrmSn=619"

# ---- 송정 ----
SJ_JSON = "http://www.hud7330.com/booking_g/sports_res_write_time.php"
SJ_PAGE = "http://www.hud7330.com/booking_g/sports_res_index.php?ca=4&toYear={y}&toMonth={m}"
SJ_COURTS = [("1코트", "5"), ("2코트", "9"), ("3코트", "10"), ("4코트", "11"), ("5코트", "12"), ("6코트", "13")]


def log(msg):
    print(f"[{dt.datetime.now(KST).strftime('%H:%M:%S')}] {msg}", flush=True)


def post_json(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest", "User-Agent": UA})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            err = e
            time.sleep(2)
    raise err


def check_spowon(date, tm):
    from playwright.sync_api import sync_playwright
    found, ok = [], 0
    ymd = date.replace("-", "")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(ignore_https_errors=True, user_agent=UA, locale="ko-KR").new_page()
        for kind in ("실외", "실내"):
            for name, pid in SP_COURTS[kind]:
                url = SP_URL.format(ymd=ymd, part=SP_PART[kind], place=pid)
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=40000)
                    pg.wait_for_selector("input[id^=checkbox_time_]", state="attached", timeout=10000)
                    r = pg.evaluate(JS_ROW, tm)
                    ok += 1
                except Exception as e:
                    log(f"  스포원 {kind} {name} 확인 실패: {str(e).splitlines()[0][:120]}")
                    r = None
                if r and r["open"]:
                    found.append(("스포원", f"{kind} {name}", url))
                time.sleep(0.3)
        b.close()
    return found, ok, 19


def check_arboretum(date, tm):
    begin, end = tm.split("~")
    found, ok = [], 0
    for i in range(1, 9):
        court = f"테니스장{i}"
        try:
            lst = post_json(ARB_JSON, {"resveGroupSn": "531", "progrmSn": "619",
                                       "resveDe": date, "resveOrd": court}).get("listOper") or []
            ok += 1
        except Exception as e:
            log(f"  수목원 {court} 확인 실패: {e}")
            continue
        for o in lst:
            if o.get("resveBeginTime") == begin and o.get("resveEndTime") == end:
                if int(o.get("resveSeatPsncpa") or 0) < int(o.get("resvePsncpa") or 1):
                    found.append(("수목원", court, ARB_PAGE))
        time.sleep(0.5)
    return found, ok, 8


def check_songjeong(date, tm):
    y, m, d = (int(x) for x in date.split("-"))
    sun = "1" if dt.date(y, m, d).weekday() >= 5 else "0"
    want = tm.replace(" ", "")
    found, ok = [], 0
    for name, gr in SJ_COURTS:
        try:
            j = post_json(SJ_JSON, {"rResDate": f"{y}-{m}-{d}", "rAsIdx": "4", "rGrIdx": gr, "sun": sun})
            if j.get("flag") != "success":
                raise RuntimeError(f"flag={j.get('flag')}")
            ok += 1
        except Exception as e:
            log(f"  송정 {name} 확인 실패: {e}")
            continue
        if any(o.get("codeId") and (o.get("codeNm") or "").replace(" ", "") == want for o in j.get("list") or []):
            found.append(("송정", name, SJ_PAGE.format(y=y, m=m)))
        time.sleep(0.5)
    return found, ok, 6


def push_phone(topic, title, message, url=None):
    if not topic:
        log("  (NTFY_TOPIC이 없어 휴대폰 알림을 보내지 않음)")
        return
    body = {"topic": topic, "title": title, "message": message, "priority": 5, "tags": ["tennis"]}
    if url:
        body["click"] = url
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    log("  휴대폰 알림 보냄")


def load(name, default):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    s = load("settings.json", {})
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    date, tm, sites = s.get("date"), s.get("time", "20:00~22:00"), s.get("sites", [])
    today = dt.datetime.now(KST).date()

    if os.environ.get("TEST_ALERT") == "true":
        push_phone(topic, "클라우드 감시 시험", "GitHub 클라우드에서 보낸 시험 알림입니다. 잘 받으셨으면 설정 완료!")

    if not s.get("on", True):
        log("settings.json에서 감시가 꺼져 있습니다 (on: false).")
        return False
    if not date or dt.date.fromisoformat(date) < today:
        log(f"감시 날짜({date})가 지났거나 없습니다. settings.json의 date를 바꾸세요.")
        return False

    log(f"확인: {', '.join(sites)} / {date} {tm}")
    found = []
    checks = {"스포원": check_spowon, "수목원": check_arboretum, "송정": check_songjeong}
    for site in sites:
        try:
            f, ok, total = checks[site](date, tm)
        except Exception as e:
            log(f"{site} 확인 전체 실패: {e}")
            continue
        log(f"{site}: {ok}/{total}개 코트 확인, 빈자리 {len(f)}곳")
        found += f

    state = load("state.json", {})
    key = f"{date} {tm}"
    alerted = set(state.get(key, []))
    now_keys = {f"{a} {b}" for a, b, _ in found}
    new = [f for f in found if f"{f[0]} {f[1]}" not in alerted]
    if new:
        courts = ", ".join(f"{a} {b}" for a, b, _ in new)
        log(f"!! 새 빈자리: {courts}")
        push_phone(topic, f"빈자리! {date[5:]} {tm}", f"{courts}\n빨리 예약하세요. (누르면 예약 페이지가 열립니다)", new[0][2])
    else:
        log("새 빈자리 없음")
    # 다시 마감된 자리는 지워서, 나중에 또 비면 다시 알린다
    state = {key: sorted(now_keys)}
    with open(os.path.join(HERE, "state.json"), "w", encoding="utf-8") as fp:
        json.dump(state, fp, ensure_ascii=False, indent=1)
    return True


if __name__ == "__main__":
    # GitHub 예약 실행은 몇 시간씩 밀릴 수 있어서, 한 번 실행되면 LOOP_HOURS 동안
    # 이 안에서 정해진 간격으로 계속 확인한다. 끝나면 워크플로가 다음 실행을 스스로 건다.
    hours = float(os.environ.get("LOOP_HOURS") or 0)
    gap = int(load("settings.json", {}).get("minutes", 30)) * 60
    end = time.time() + hours * 3600
    while True:
        if not main():
            open(os.path.join(HERE, "stop"), "w").close()   # 감시 끝 → 다음 실행 걸지 않음
            break
        if time.time() + gap > end:
            break
        log(f"{gap // 60}분 뒤 다시 확인")
        time.sleep(gap)
