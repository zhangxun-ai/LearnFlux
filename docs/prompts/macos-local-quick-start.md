# 新手安装与真实链接验收：给 Agent 的提示词

复制下面整段，发给 WorkBuddy、Codex、Claude Code 等能操作本机终端和浏览器的 Agent。目标是让你常用的平台真实可用：解析真实链接，取得正文或语音转录，生成 AI 解读，导出后仍能从历史记录打开。粘贴示例文字只用于排错，不作为最终验收。

先选择要使用的平台与转录方式。平台可以多选，选中的平台应分别验证；不需要一次安装所有外部集成。全新安装默认 SQLite，已有 PostgreSQL 保留原连接。真实 Key 只在自己的电脑填写。

| 需要什么 | 负责什么 | 什么时候配置 |
| --- | --- | --- |
| DeepSeek 或已有兼容模型服务 | 校对、总结、问答 | 真实 AI 解读需要 |
| TikHub API Key | 抖音、小红书等来源解析与下载信息 | 选择对应来源时；不是模型或 ASR Key |
| FFmpeg + 本地 ASR | 将音视频语音转为文字 | 选择本地转录，或验证无字幕视频时 |
| 云端 ASR 凭据 | 将音视频提交到云端识别 | 选择云端转录；有独立费用与报价确认 |

当前普通链接 `local` 策略走 MLX Whisper，项目安装路径只支持 Apple Silicon Mac；Intel Mac、Linux、Windows 不能照搬。YouTube 字幕、小红书图文与已缓存结果都可能不经过 ASR，必须分别说明实际路径。非 Apple Silicon 平台需要按当前实现选择可用的云端方案，或明确报告本地转录兼容缺口。

```text
我是第一次使用 LearnFlux，不懂 Git、数据库和终端。请直接操作我的电脑完成安装和真实链接验收；需要我亲自输入凭据、登录或确认费用时，用中文告诉我在哪个窗口操作、成功后应看到什么。不要只给命令后结束，也不要把示例文字或模拟响应当作真实功能已可用。

项目地址：https://github.com/zhangxun-ai/LearnFlux
最终目标：我选择的平台真实链接 → 解析/下载 → 可用字幕、正文或真实 ASR → DeepSeek 等模型校对与解读 → 查看/导出 → 历史记录持久保存。

1. 先用一次简短沟通确认：我要用的平台（YouTube / 抖音 / 小红书，可多选）、希望本地还是云端转录、真实样例链接及可接受费用范围。
   我不了解时解释各服务用途，结合电脑推荐方案。样例优先用我提供且有权处理的短内容；没有样例时帮我寻找公开可访问、确有内容的短链接，不编造视频ID，不使用私密资料或默认读取浏览器Cookie。
   所有选中平台都要各有实际结果；只验证YouTube不能声称抖音、小红书也已成功。若要验证ASR，至少选择一条未处理过、需要语音识别的口播短视频；小红书须选视频笔记，抖音不要用尚未确认支持的图集代替视频。

2. 阅读 README、AGENTS.md、.env.example、scripts/bootstrap.sh、server.sh、docs/guides/configuration.md 和 docs/guides/quickstart.md，核对实际版本与平台能力。
   复用已有仓库、配置、数据库和服务；没有仓库时选择用户可写目录并克隆。检查系统、CPU、网络、磁盘、Git、Bash、curl、lsof、uv、Python和8000端口；按当前官方说明安装缺少依赖。
   我授权安装项目所需依赖；管理员权限、付费调用、购买服务、开放公网、清空或迁移既有数据需先取得同意。已经同意的平台、样例和费用范围内继续执行，不对同一事项重复询问。

3. 在项目根目录仅当 .env 不存在时从 .env.example 复制，并设置 chmod 600 .env。已有文件只补缺项，不覆盖真实值。
   确认 .env、私有config和数据库被Git忽略；真实Key、数据库URL、Cookie、结果访问令牌不得进入源码、模板、命令参数、聊天、日志、截图或Git。不要把.env作为Shell脚本执行。
   在本机安全核对已有凭据，只报告“已配置/缺少”，不显示值。新安装默认sqlite/local并自动初始化；已有PostgreSQL复用。选择新装PostgreSQL时按 docs/guides/postgresql.md 建专用账号与库，配置DATABASE_URL，启动自动迁移并只读核对表结构；不把用户库当写删测试库。

4. 首次安装或确实缺少依赖时使用 scripts/bootstrap.sh 准备环境；需要音视频时运行 bash scripts/bootstrap.sh --with-media，确保 FFmpeg / ffprobe 实际可运行。该脚本不会启动服务。FFmpeg缺失时macOS需先有Homebrew，Ubuntu/Debian需apt-get及安装权限，其他发行版先自行安装FFmpeg。日常启动使用 bash server.sh start，不重复安装。
   bootstrap 不会替我开通 TikHub、DeepSeek 或云端 ASR，也不会因为页面能打开就代表转录引擎已经安装。

5. 默认引导我准备DeepSeek API Key；已有可用兼容模型服务时可复用，不强迫换服务。
   在我自己的.env填写 LEARNFLUX_LLM_API_KEY、LEARNFLUX_LLM_BASE_URL、LEARNFLUX_LLM_MODEL。DeepSeek Key来自官方控制台 https://platform.deepseek.com/api_keys；接口地址按官方OpenAI兼容说明填写，模型用当前账号实际可调用的ID，不照搬旧模型名。
   注意官方SDK示例中的DEEPSEEK_API_KEY不是本项目的读取名称。通用MODEL用于校对、总结和问答，按需覆盖具体任务模型；非空环境变量优先于设置页。不要把DeepSeek Key当成ASR Key，也不要把“Key不为空”当作已成功调用。
   复用其他兼容服务时同时核对私有llm.model_endpoints：模板把qwen*路由到仅读DASHSCOPE_API_KEY的百炼次级端点。若希望Qwen走主端点，先调整相应路由；若保留次级端点，配好它的Key，不能只填主LLM三项就声称已可用。

6. 我要使用抖音或小红书时，引导我在TikHub用户中心 https://user.tikhub.io/dashboard/api 创建或取得自己的API Token，填本机.env的 LEARNFLUX_TIKHUB_API_KEY；接口域名用当前官方推荐地址，LEARNFLUX_TIKHUB_BASE_URL可按需覆盖。
   确认账号可调用所需平台接口及已接受费用范围，再通过项目实际解析所选链接；不能只检查Token格式，不能默认认为查账号、测Key或重试免费。
   YouTube可用字幕路径通常不需要TikHub，不为了文字或字幕学习强制购买全部服务。小红书图文提取成功只代表正文链路成功，不代表视频下载/转录已验证。

7. 按我选择的转录方式配置并验证，不自动切换到另一种付费方式：
   A. 本地：Apple Silicon Mac使用 bash scripts/bootstrap.sh --with-local-whisper，准备FFmpeg、独立mlx-whisper环境和模型，并按脚本输出在私有config/config.jsonc设置local_whisper的binary、model、enabled等。
      首次模型下载前说明资源需求，核对可执行程序，再用真实无字幕口播视频确认实际执行ASR并得到非空、与语音一致的文字。仅安装Python依赖或连通端口不算成功。
      普通链接明确local时当前固定走MLX Whisper，不会因enabled=false回退CapsWriter。Intel Mac/Linux/Windows不能套用此安装；若我坚持本地且代码不支持，说明兼容缺口，不只填CapsWriter地址便宣称完成，也不擅自改业务代码。
   B. 云端：当前项目支持百炼云端ASR。引导我在本机.env填写 DASHSCOPE_API_KEY、DASHSCOPE_WORKSPACE_ID、DASHSCOPE_API_HOST，Host须与同一Workspace北京节点匹配；按配置指南显式启用cloud_asr.enabled。
      DeepSeek/TikHub Key不能替代这三项。选择cloud策略；音频准备后的页面报价仍需我确认费用上限，未确认不提交付费任务。等待同一任务结果，不盲目重发状态未知的提交，不自动充值。
   若真实链接使用平台字幕、图文正文或缓存，不会因此证明任一本地/云端ASR已可用。需要验ASR时另外选未缓存且确需转录的短视频，不清空历史或伪造成功。

8. 用 bash server.sh start 后台启动，实际地址以日志与配置为准，默认 http://127.0.0.1:8000；环境变更后用 restart，status / log检查，stop停止。
   不重复启动或结束陌生进程。macOS创建用户级登录启动项，stop会卸载；Ctrl+C只退出日志或停止前台进程。先检查页面、选定数据库和必要服务，再验证真实处理。
   原始媒体可能发给云ASR，转录正文可能发给模型，链接可能发给TikHub；真实调用前说明哪些服务会收到内容与可能费用，取得我对本次范围的同意，不上传无关或私密资料。

9. 在项目“单篇深度学习”粘贴选中的真实链接，选择已配置的转录方式并提交；有云ASR报价时按产品流程确认，等待任务真正完成。
   分别核对：标题/作者/来源是否正确；实际取得的是字幕、图文正文还是ASR转录；内容是否与原始视频/文章对应并覆盖所选内容；AI校对和解读是否真实生成且与原文一致；导出的原文/解读能否打开且内容完整。
   标明是否命中已有缓存。YouTube字幕成功只验收字幕链路；若ASR未运行，不能在ASR栏写通过。不能仅凭页面上遗留的“CapsWriter”标签判定实际引擎，要核对任务阶段、运行记录和产物。
   刷新后从历史记录重新打开结果；可安全停止的新实例再重启检查持久保存。已有工作中的实例不未经同意中断，不为测试删旧数据。
   示例文字只可辅助定位模型或页面问题，最终仍须回到真实链接，不以示例任务、模型列表响应、已受理状态或mock代替完成。

10. 失败就根据真实错误定位：区分链接/登录/限流、TikHub额度或权限、下载/FFmpeg、本地ASR安装/模型、云ASR授权/报价、DeepSeek模型/Key等问题。
    在授权范围内修复并继续，收费重试受预算约束，提交状态不明时先核对同一任务。不能随意换一条已知能跑的链接来冒充原目标平台通过。
    缺少凭据、人工授权、预算或平台兼容性时给我明确的本机操作步骤；能独立继续的准备工作继续做，但这条真实链路保留为未完成，不声称已能使用全部功能。

11. 最后按平台、实际内容路径与转录方式给结果表：样例来源、解析/下载、字幕/ASR、真实AI解读、查看/导出、持久化各项分别标注通过、失败或未验证，附可打开的结果与导出位置（不公开带令牌的私密链接）。
    只有选中平台的真实内容取得、AI解读和查看导出均通过，才称该平台已跑通；承诺支持本地/云ASR时，所选ASR也须真实识别成功。只测一条模式不代表另一条模式通过。
    给出本机入口、缺少项、日常启停方式和已验证范围。最后确认没有把真实.env、数据库、Cookie或密钥加入Git；不替我提交或推送代码，也不默认开启手机公网、飞书归档、OCR或付费生图。
```

服务字段与获取入口见[配置指南](../guides/configuration.md)，数据库见 [PostgreSQL 指南](../guides/postgresql.md)。手机收集、飞书归档等附加集成见[按需服务提示词](optional-services.md)。配置事实以当前代码为准；实际平台成功与本地离线测试是两类证据。
