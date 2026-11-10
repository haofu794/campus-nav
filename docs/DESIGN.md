# 设计记录

这里记的是项目里每个决定的理由，以及为什么没选别的办法。面试被问到时，看这一页就够了。

## 1. 为什么抓 JSON API，不解析 HTML

现在的招聘网站大多先返回一个空的 HTML 骨架，再用 JavaScript 请求 JSON API 拿岗位数据。直接请求那个 API：

- 体积小：一页 HTML 可能有 300 KB，里面真正的数据只有 10 KB 左右
- 结构清楚：字段名直接告诉你含义（title、city），不用从 `<div>` 里抠
- 更稳定：网站改样式时 HTML 结构会变，API 字段很少变

没用 Playwright / Selenium 这类无界面浏览器：它们每个页面都要完整加载一遍，慢几十倍，放进 GitHub Actions 每天跑几百个网站不现实。只在找不到 API 时才考虑。

Moka 的接口返回是加密的，不破解，只保留官网入口。

「找不到 API」的真实例子：方太用的是北森老版门户。我在浏览器的 Network 面板里看，打开岗位页时除了一个登录状态检查，没有任何岗位数据请求，岗位是服务器直接写进 HTML 的（`/campus/?PageIndex=N`，每页 10 个）。这种情况下只能解析 HTML。程序先 POST 新版接口，如果返回 302 跳转到 404，就判定是老版门户，改走 HTML 解析。

## 2. 各个来源的细节（2026-11 实测）

| 来源 | 接口 | 分页 | 校招/实习怎么区分 | 详情页链接 |
|---|---|---|---|---|
| 飞书 | POST /api/v1/csrf/token，再 POST /api/v1/search/job/posts | limit / offset，limit 100 可用 | recruit_type.parent = 校招，recruit_type.name = 实习 | {base}/{path}/position/{id}/detail |
| 北森 | POST /api/Jobad/GetJobAdPageList | PageIndex 从 0 开始，PageSize 100 可用 | Category ["2"] / ["3"] | {base}/campus/detail?jobAdId={Id} |
| 国聘 | POST gp-api.iguopin.com/api/jobs/v1/list | page 从 1 开始，page_size ≤ 50，最多 20 页 | nature ["115xW5oQ"] 校招 / ["11bTac9"] 实习 | www.iguopin.com/job/detail?id={job_id} |
| campus-radar | GET ajax-1.github.io/campus-radar/data/jobs.json | 一次全量 | 数组第 5 项 is_intern | 数组里自带 |
| 中国平安 | POST campus.pingan.com/zztj-recruit-talent-webserver/.../positionSearch/queryPositionPage | PageNum 从 1 开始，pageSize 100 可用，返回 totalPage | positionType "1" 应届 / "2" 实习 | campus.pingan.com/positionDetail?positionId={idPosition} |
| 大易（新版） | POST {host}/wecruit/positionInfo/listPosition/{SU 租户号}，表单格式 | currentPage 从 1 开始，服务器限制每页 12 或 50 条，按 totalPage 翻页 | 只抓 recruitType=1，实习看标题 | {host}/{SU}/pb/posDetail.html?postId=..&postType=campus |
| 大易（旧版） | GET {host}/wt/{代码}/mobweb/jsonp/position/list | page 从 1 开始，rowSize 50，返回 pageCount | 只抓 recruitType=1 | {host}/wt/{代码}/mobweb/v8/position/detail?postId=.. |

踩过的坑：

- 飞书不带 `website-path` 请求头，会默认返回社招岗位
- 国聘的 district 参数要写成 `["000000.310000"]` 这种完整编码，写 `["310000"]` 返回 0 条
- 国聘请求太快会直接断开连接，所以间隔设成 1.2 秒
- 飞书短链接（/s/xxxx）其实是普通的 302 跳转，但跳转后的页面对非浏览器客户端返回 404。第一版跟随了跳转，结果因为 404 放弃了。修正：不跟随跳转，只读 Location 响应头，从里面取出门户路径
- 北森有的租户（上海银行）从国外访问一页要 8 秒左右，超时时间设成了 45 秒
- 大易子域名（goertek.hotjob.cn）的首页里找不到租户号，要 POST /wecruit/common/getSLD 并带上表单字段 sld=完整域名才能拿到；不带这个字段，接口只返回「二级域名不可为空」
- 大易的 recruitType 编号各家不统一：伊利的 type 3 返回了 1000 多个「灌装工段长」这类社招岗位。第一版把 type 3 当成实习，多出 1835 条错误数据。现在只抓 type 1，实习按标题判断
- 广发证券、迪卡侬、湘电集团这类自定义域名的大易，页面能打开，但接口不返回 JSON。同一个租户号放到大易官方域名 wecruit.hotjob.cn 上就能用，程序会自动回退

## 3. 自动识别招聘系统（scraper/detect.py）

公司名单里有将近 800 个官网不是飞书或北森的标准网址。用户要求「全覆盖」，一家一家手写爬虫做不完，所以先做识别：

1. 访问官网（跟随跳转），看最终网址和页面内容里有没有各个系统的特征：`jobs.feishu.cn` 或 `atsx` 是飞书，`zhiye.com` 或 `beisen` 是北森，`hotjob` 是大易，`mokahr` 是 Moka
2. 用一次接口调用验证，同时找出爬虫需要的参数：飞书要门户路径（依次试网址里的第一段、campus、index……），大易要 SU 租户号或旧版的公司代码
3. 结果缓存 7 天，存在 `data/platform_cache.json`，每天的定时运行不用重新访问 800 个网站

2026-11-10 的识别结果：北森 206、飞书 48、大易 32、Moka 86、真正自研 413、连不上 136、只有公众号/邮箱 81。

识别不出来的公司也不会被丢掉，都进「公司目录」，展示投递说明和入口。我的判断是：投递说明本身就很有价值，「全覆盖」首先是信息全覆盖，岗位级的覆盖再逐步提高。

为什么不用无界面浏览器去抓那 413 个自研网站：每个网站的页面结构都不一样，通用的「读页面」方法拿到的数据质量很差（不知道哪段是标题、哪段是城市），而且每天打开 400 个网站，在 GitHub Actions 上又慢又不稳定。逐个找 JSON 接口虽然慢，但抓到的数据是干净的。

## 4. 礼貌抓取

- 每个来源内部串行请求，请求之间间隔 0.8–1.2 秒，外加随机抖动
- 6 个线程并行，但每个线程访问的是不同的网站，所以单个网站感受到的压力不变
- 失败后按 2、4、8 秒指数退避重试，3 次还不行就放弃这个来源
- campus-radar 已经抓了 17 家大厂，我直接用它的索引，不重复去访问这些网站

## 5. ETL 的顺序

失败兜底 → 标准化 → 黑名单 → 去重 → 生命周期

去重有两层：URL 相同直接去掉；(公司, 标题, 校招/实习) 相同、但来自不同平台的，合并成一条，城市取并集。同一个平台内部标题相同的不合并，因为通常是不同团队，各有自己的详情页。来源优先级：官网 > 国聘，因为国聘是聚合平台。

城市统一的例子：北森的「江苏省·南京市/苏州市」变成 [南京, 苏州]，国聘的「无锡-锡山区」变成 [无锡]，英文的 Beijing 变成 北京。

方向分类用关键词规则，不用 LLM。每天 2 万个岗位，规则免费、瞬间完成，分错了也能看出是哪个词导致的。

第一版只有一层关键词，标题里出现「AI」「大模型」就归到算法/AI。结果 6191 个 AI 岗位里，至少 1148 个标题明显是运营、产品、销售，比如「AI Agent 产品经理」「大模型运营实习生」。第二版改成三层：

1. 强关键词：表示岗位角色的词（算法、前端、测试、数据分析、运营、产品经理……），命中就直接定
2. 数据源自带的类别字段（campus-radar 和飞书都会给），能明确对应上就用
3. 弱关键词：表示话题的词（AI、大模型、Agent、开发……），前两层都没命中时才用

另外两个细节：先去掉「 - 团队名」后缀，比如「算法工程师 - Seed 产品研发」里的「产品」不参与判断；判断角色时忽略括号里的内容，因为括号里一般写的是业务领域，比如「全栈开发（电商营销）」。改完之后，算法/AI 从 6191 个降到约 3500 个，抽查下来基本都是真正的技术岗。

## 6. 每日更新

- 一条命令跑完：`python run.py`。它是幂等的，每次都从头重新生成 data.json，不在旧文件上追加
- GitHub Actions 定时跑，cron `0 23 * * *` 是 UTC 时间，对应北京时间早上 7 点
- first_seen / last_seen 记录每个岗位的生命周期。网页上能标出「新」；一个岗位连续 3 天没再出现才算下架
- 某个来源失败时沿用它昨天的数据
- 总数比昨天少一半以上就不写入。真实情况下不会一夜之间少一半岗位，出现这种情况多半是程序出了问题

## 7. 为什么只给自己用

一开始考虑过公开给别人用，后来放弃了，原因是：

- 网页是纯静态的，API key 写进前端谁都能偷走；要在线处理每个访问者的简历，就得加后端、做限流，费用也得我出
- 国内访问 github.io / vercel.app 不稳定，真要稳定就得用国内服务器、做 ICP 备案
- 把抓来的数据公开分发，比自己用的合规风险高

只给自己用之后，简历只有一份，可以离线用 LLM 处理一次，网页只负责显示算好的分数。代码以后仍然可以开源（不带 profile.json 和数据）。

## 8. 匹配：召回 → 排序 → 重排

公式和数字例子写在 `matching/bm25.py`、`matching/rank.py`、`matching/evaluate.py` 的注释里。这里只记取舍：

- 为什么两路召回：BM25 只认字面，「智能体」和「Agent」对不上；embedding 能识别同义，但比较模糊，「Java 后端」和「Python 后端」在它看来很像。两路各选 1000 个取并集，互相补漏
- 为什么用 bge-small-zh + fastembed：模型小（约 90 MB），以中文为主；fastembed 用 ONNX 在 CPU 上跑，不用为了推理装 800 MB 的 PyTorch
- embedding 缓存按「岗位 ID + 标题」的哈希存，每天只给新岗位算向量。第一版是按 JD 全文的哈希存的，结果从前一天沿用下来的岗位（data.json 里不存 JD 全文）每次都对不上缓存，只能重算，而且算出来的向量信息更少。GitHub Actions 里用 actions/cache 保存模型和缓存
- 网页上传简历时为什么没有 embedding：模型要在浏览器里跑，得下载几十 MB 再用 transformers.js。只给自己用的话，用 Python 生成 profile.json 更简单，所以网页端只用 BM25 + 技能匹配，并在页面上标明
- 为什么用 BM25 而不是关键词计数：计数会偏向把所有热门词都列一遍的长 JD，而且把常见的「Python」和少见的「RAG」看得一样重。BM25 用 IDF 和长度归一化解决了这两个问题
- 为什么特征要先缩放到 0–1：BM25 原始分可能是 0–40，不缩放的话，0/1 取值的方向、城市特征就基本不起作用
- 为什么技能重合度的分母要 +1：岗位只有一个技能标签、刚好我会的话，不应该直接拿满分 1.0
- 为什么做 MMR：只按匹配分排序，前几十名可能全是同一家公司。λ = 0.7 是牺牲一点相关性换多样性
- 为什么还没做 learning to rank：只有我一个用户，投递记录最多几十条，拿来训练模型只会过拟合。先用人工定的权重，等投递记录攒多了，再考虑用 logistic regression 去调

评估用人工标注 100 个岗位（50 个高分 + 50 个随机），算 NDCG@10 / NDCG@20，对比 skill_only、bm25_only、emb_only、bm25+emb、combined 五种排序。这样能直接看出加 embedding 这一路到底有没有带来提升。

## 9. 路线图

- v1（已完成）：四个来源 → ETL → 本地网页（筛选、校招/实习分区、投递进度）→ Actions 每日更新
- v2（已完成）：简历提取（网页上传或命令行）→ BM25 + embedding 两路召回 → 加权排序 → MMR → 离线评估
- 待做：自建招聘系统的银行（国有大行、兴业等）；国聘超过 1000 条时按类别再拆分；根据投递反馈调整权重
