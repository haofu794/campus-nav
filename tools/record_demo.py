"""Record a demo walkthrough of the page with headless Chrome.

Usage: python demo.py PORT OUTDIR   (page served at http://localhost:PORT)
Produces OUTDIR/*.webm; convert with ffmpeg afterwards.
"""
import asyncio
import sys

from playwright.async_api import async_playwright

W, H = 1280, 800

CAPTION_JS = """
(text) => {
  let el = document.getElementById('__cap');
  if (!el) {
    el = document.createElement('div'); el.id = '__cap';
    Object.assign(el.style, {position:'fixed', left:'50%', bottom:'28px', transform:'translateX(-50%)',
      background:'rgba(29,33,41,.88)', color:'#fff', padding:'10px 22px', borderRadius:'22px',
      font:'500 17px -apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif', zIndex:99999,
      boxShadow:'0 6px 24px rgba(0,0,0,.25)', transition:'opacity .25s'});
    document.body.appendChild(el);
  }
  el.textContent = text; el.style.opacity = text ? 1 : 0;
}
"""

# Visible fake cursor, since headless recordings don't show the mouse.
CURSOR_JS = """
() => {
  const c = document.createElement('div'); c.id = '__cur';
  Object.assign(c.style, {position:'fixed', left:'0', top:'0', width:'18px', height:'18px', borderRadius:'50%',
    background:'rgba(0,168,112,.35)', border:'2px solid #00a870', zIndex:100000, pointerEvents:'none',
    transform:'translate(-50%,-50%)', transition:'left .35s ease, top .35s ease'});
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
}
"""


async def main(port, outdir):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": W, "height": H}, record_video_dir=outdir,
                                  record_video_size={"width": W, "height": H}, locale="zh-CN")
        pg = await ctx.new_page()
        await pg.goto(f"http://localhost:{port}/index.html")
        await pg.wait_for_selector("#list article", timeout=60000)
        await pg.evaluate(CURSOR_JS)
        cap = lambda t: pg.evaluate(CAPTION_JS, t)
        wait = pg.wait_for_timeout

        async def move_to(sel, click=True):
            box = await pg.locator(sel).first.bounding_box()
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            await pg.mouse.move(x, y, steps=12)
            await wait(250)
            if click:
                await pg.mouse.click(x, y)

        await cap("每天自动聚合 1000+ 家企业的 2027 届校招与实习岗位")
        await wait(2600)

        await cap("① 搜索：公司、岗位、技能都能搜，多个词用空格分隔")
        await move_to("#q")
        await pg.keyboard.type("Agent 上海", delay=140)
        await wait(2200)
        await pg.fill("#q", "")
        await pg.dispatch_event("#q", "input")
        await wait(600)

        await cap("② 筛选：企业类型、方向、城市可以组合")
        await move_to('#ent .chip:has-text("互联网大厂")')
        await wait(900)
        await move_to("#direction", click=False)
        await pg.select_option("#direction", value="AI应用/Agent")
        await wait(900)
        await pg.select_option("#city", value="上海")
        await wait(2000)
        await pg.select_option("#direction", index=0)
        await pg.select_option("#city", index=0)
        await move_to('#ent .chip:has-text("互联网大厂")')
        await wait(600)

        await cap("③ 简历匹配：上传或粘贴简历，在本机识别技能并重新排序")
        await move_to("#resume summary")
        await wait(700)
        await move_to("#resume-text")
        await pg.keyboard.type("熟悉 Java、Spring Boot、MySQL、Redis，做过 Kafka 消息队列和微服务项目", delay=35)
        await wait(500)
        await move_to("#resume-extract")
        await wait(1200)
        await move_to("#resume-apply")
        await wait(2600)
        await cap("绿色标签是你会的技能；分数和顺序都按你的简历重新计算")
        await wait(2600)
        await move_to("#resume summary")
        await wait(400)

        await cap("④ 投递管理：给岗位标记状态，「我的投递」统一跟进")
        await pg.mouse.wheel(0, 180)
        await wait(600)
        sel = pg.locator("select[data-id]").first
        await move_to("select[data-id]", click=False)
        await sel.select_option("已投递")
        await wait(900)
        sel2 = pg.locator("select[data-id]").nth(1)
        box = await sel2.bounding_box()
        await pg.mouse.move(box["x"] + 40, box["y"] + 14, steps=10)
        await sel2.select_option("想投")
        await wait(1200)
        await pg.mouse.wheel(0, -400)
        await move_to('#tabs [data-tab="mine"]')
        await wait(2400)

        await cap("⑤ 公司目录：抓不到岗位的公司也收录了官网入口和投递说明")
        await move_to('#tabs [data-tab="companies"]')
        await wait(1200)
        await pg.select_option("#cstatus", "note")
        await wait(1800)
        await pg.select_option("#cstatus", "")
        await move_to("#q")
        await pg.keyboard.type("平安", delay=150)
        await wait(1500)
        btn = pg.locator(".see-jobs").first
        if await btn.count():
            await move_to(".see-jobs")
            await wait(2600)

        await cap("投递全部跳转企业官网 · 进度只保存在你自己的浏览器")
        await wait(2800)
        await cap("")
        await wait(400)
        await ctx.close()
        await b.close()


asyncio.run(main(sys.argv[1], sys.argv[2]))
