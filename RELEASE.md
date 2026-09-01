# 发布手册 / Release Manual

iterate 生态目前有 **三个** 会独立对外发布的项目。本手册把它们所有的发布渠道、
命令、前置步骤、版本同步规则与已知坑整理在一起，作为每次发版的统一 checklist，
避免遗漏。

> 发布架构总览见 [`DESIGN-iterate-harness.md`](DESIGN-iterate-harness.md) §6「仓库形态」与各版本迭代记录。

---

## 生态项目一览

| 项目 | 仓库 | 分发渠道 | 版本线 |
|---|---|---|---|
| **iterate-skill**（skill 本体 + CLI + 安装器） | `jingzhao-l/iterate-skill`（主仓库，唯一维护点） | GitHub Release / npm / ClawHub / ModelScope / Tencent SkillHub | 2.9.x（与 skill 同步） |
| **iterate-harness**（Python 引擎 + npm 包装器） | `jingzhao-l/iterate-harness`（subtree 独立发布仓） | GitHub tag / npm 包装器 | 1.9.x（独立） |
| **iterate-plugin**（dsh 插件） | `jingzhao-l/iterate-plugin`（subtree 独立发布仓） | npm | 2.12.x（独立，自 2.3.7 起） |

三个项目共用同一主仓库 `jingzhao-l/iterate-skill` 作为唯一开发/评审点，
`harness/` 下的两个子项目通过 `git subtree` 拆分到各自的独立发布仓库，再在
`.release/` 发布工作区执行 npm 发布。

---

## 项目 1：iterate-skill（skill 本体）

### ⚠️ 核心规范（skill 就是 skill，发布前必读）

> **skill 发布只发 skill 本体，`harness/` 下的两个独立子项目一律排除。**
>
> 生态里 `harness/iterate-plugin`（dsh 插件）与 `harness/iterate-harness`（Python 引擎）
> 各有自己的分发仓库（`jingzhao-l/iterate-plugin` / `jingzhao-l/iterate-harness`），
> **不属于 skill 分发包**。任何平台（ClawHub / ModelScope / SkillHub / GitHub release
> tarball）的 skill 发布包都不得携带 `harness/*` 源码。
>
> - 失效规范示例（历史误报，已废弃）：2.3.14/2.3.15 曾把 `harness/iterate-plugin`
>   完整源码夹带进 ModelScope 与旧 SkillHub 包，全部跳过。
> - **自 2.3.16 起所有平台包均剔除 `harness/*`。**
> - **发布前强制复核**：任意平台的包/目录发出前，先跑
>   `unzip -l <zip> | grep harness/`（zip）或 `find <stage目录> -path '*/harness/*'`（stage 目录），
>   结果为 **0 条**才允许发出。
>
> 每步发布清单中凡是碰包的，都会在对应步骤再次带回这条提醒。

### 需要同步的版本号文件

发版前必须同步以下文件的版本号（step 1 一次性完成）：

| 文件 | 字段 |
|---|---|
| `pyproject.toml` | `[project].version` |
| `iterate_cli/__init__.py` | `__version__` |
| `SKILL.md` | frontmatter `version` |
| `npm-installer/package.json` | `version` |
| `CHANGELOG.md` | 新增版本条目 |

> **核心规范（参见上文 ⚠️ 总则）**：skill 分发包只发 skill 本体，
> `harness/` 下两个独立子项目一律排除、不得携带。自 2.3.16 起所有平台包均剔除 `harness/*`。
> 重建/发布前用 `unzip -l <zip> | grep harness/` 复核必须为 0。

### 发布清单

- [ ] **1. 同步版本号**：人工编辑上述 5 个文件 + 更新 `CHANGELOG.md`（保留旧版本条目，只新增）。
- [ ] **2. 本地验证**：跑通全部测试（`pytest tests/ -q`、`ruff check`），确认 `iterate --version` 输出新版本。
- [ ] **3. 提交并推送主仓库**：`git add -A && git commit && git push origin main`。
- [x] **4. 打 GitHub Release tag**：`git tag v<X.Y.Z> && git push origin v<X.Y.Z>`，在 GitHub 创建 Release。
      > `.github/workflows/release.yml` 会在 Release published 时自动生成并上传
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt`（从 tag 树确定性构建）。
      > **（skill 只发 skill）**：`git archive` 使用 pathspec `':!harness'` 剔除 harness，tarball 不含 `harness/`。
- [x] **5. 发布 npm 安装器**（安装器从 GitHub Release 下载 tarball，务必先于/同步于 npm 发布）：
      ```bash
      cd npm-installer
      npm publish
      ```
      验证：`npx iterate-skill-installer --version` 能拉到新版本。
- [x] **6. 发布 ClawHub**：
      ```bash
      clawhub publish <stage 目录> --slug iterate-skill --name Iterate --version <X.Y.Z> --no-input
      ```
      > **坑**：必须显式传 `--name Iterate`，否则显示名会被默认取为发布目录 basename
      > （历史上出现过 `Clawhub Stage 2.3.12`）。ClawHub 有已知 bug（issue #2983），
      > 偶发 `skillId/versionId invalid value`，发布前需清理残留的 suspended 进程。
      >
      > **串行上传慢**：ClawHub 逐文件串行上传慢网络下极易假死，可用并发脚本
      > `.dist_tmp/clawhub_publish.py`（`--concurrency N`）并行上传。
      >
      > **stage 必须干净（skill 只发 skill）**：stage 目录不得含任何 `harness/` 子项目
      > （`harness/iterate-harness`、`harness/iterate-plugin` 均为 0；历史 2.3.14–2.3.16
      > 误打包 65MB clone 超 50MB 上限）。
      > 发布前复核：`find <stage目录> -path '*/harness/*'` 结果为空。
      >
      > 唯一可发的纯 skill 本体文件集就是 `git archive ':!harness'` 产出的 tarball 解包结果。
- [x] **7. 发布 ModelScope**（skill 只发 skill）：
      - 用 **精简包**（重建脚本 `.dist_tmp/rebuild_ms.py` 已剔除 `harness/*`）。
      - zip 需 < 5MiB；通过 OpenAPI 更新：`openapi.update_skill_settings(owner, name, {'skill_file': file_id})`。
      > **坑**：完整包常超 5MiB 上限，必须用精简包；且历史版本曾夹带 `harness/iterate-plugin`
      > 源码，重构后必须为 0。发出前复核 `unzip -l <ms.zip> | grep harness/` 为空。
- [x] **8. 发布 Tencent SkillHub**（skill 只发 skill）：
      - 用 **SkillHub 专用包 `iterate-skill-skillhub.zip`**（重建脚本 `.dist_tmp/rebuild_skillhub.py`
        在剔 harness 的 ms 精简包基础上**再剔除 LICENSE**），skillId `104490`。
      - **发布命令（skillhub CLI）**：本地工具 `~/.local/bin/skillhub`（源码在
        `~/.skillhub/skills_store_cli.py`），自动读取登录凭证
        `~/.skillhub/credentials.json`（个人社区版 `skh_` key）：
        ```bash
        ~/.local/bin/skillhub publish <skillhub.zip 或目录> \
          --version <X.Y.Z> --changelog "<本次变更一句话>" --json
        ```
        > CLI 内部调用 `POST https://api.skillhub.cn/api/v1/community/skills/publish`，
        > multipart 上传（`payload` JSON 含 slug/version/displayName/summary/.../changelog
        > + 每个 skill 文件一个 `files` part，filename 存相对路径）。
        > 返回 JSON `{"ok":true,"skillId":104490,"version":"<X.Y.Z>","versionId":...,"tags":{"latest":"<X.Y.Z>"},"reviewStatus":"pending","securityScanStatus":"pending"}`。
        > `reviewStatus/securityScanStatus=pending` 为平台异步审核，与既往一致，非失败。
        > 可选 `--dry-run --json` 做本地预检（只校验 metadata+打包，不发 HTTP）。
      > **坑**：必须用去掉 LICENSE 的精简专用包（约 288KB）防止上传 `Broken pipe`；
      > 完整包（含 LICENSE）会因过大上传失败。该专用包源自剔 harness 的 ms 精简包，
      > 故天然不含 `harness/`；发出前仍复核 `unzip -l <skillhub.zip> | grep harness/` 为空
      > （0 条）且 `unzip -p <zip> SKILL.md | grep ^version:` 已是 `<X.Y.Z>`。
      >
      > **无法同版本重传**：SkillHub 对已发布版本上锁，重传必须升版本（本手册 2.3.17
      > 即因清理 harness 后同版本被锁而统一升版覆盖）。
- [x] **9. 三平台版本一致性确认**：ClawHub / ModelScope / SkillHub 均指向 `<X.Y.Z>`。
      > **2.11.2 状态（2026-09-01）**：GitHub Release v2.11.2 已发布（tag `v2.11.2`，CI 自动生成
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt` + `iterate-qoder.zip`，`:!harness` 剔除 harness，
      > 本地 `sha256sum -c` 通过、tar 解包后 `harness/*` 为 0）；npm `iterate-skill-installer@2.11.2`
      > 已发布（`npm view` 确认 latest=2.11.2，`npx -y iterate-skill-installer@2.11.2 --version` 输出
      > 2.11.2）；ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本
      > `.dist_tmp/clawhub_publish.py` + `clawhub-stage-2.11.2/iterate-skill`（72 文件、1,503,797 字节）
      > 发布 2.11.2（响应 `ok:true`、`status=pending`，versionId `k97e8fhws61rx9jmhq38b4mn2d8djnez`，
      > 发布前 resolve 显示 `latestVersion: 2.11.1`；首次上传遇 Convex read-timeout 被中止，重试后成功）；
      > ModelScope 已 PATCH 生效（`.dist_tmp/rebuild_ms_2112.py` 重建 2.11.2 精简 zip 432,648 字节、
      > 70 文件，`update_skill_settings` success，file_id `c04caaee-92f2-47d9-8b4c-7c58be35f8bf`，
      > `get_skill` last_modified 更新至 2026-09-01T13:49:21Z）；SkillHub（skillId `104490`）
      > `skillhub publish` 成功（`ok:true`，66 文件、430,316 字节，versionId `281031`，
      > `tags.latest=2.11.2`，`reviewStatus/securityScanStatus/contentAuditStatus=pending` 为平台异步审核）。
      > 2.11.2 核心变更（纯修复版 patch）：refresh 调和结果真正落盘、doctor 畸形白名单不再绕过
      > 元字符安全网、wizard 重跑基础配置不再丢弃数据、validate.py 重定义区块切分双重偏移、
      > publish_qoder 幂等标记字符不一致；含新回归测试（test_refresh_reconcile/test_publish_qoder 等）。
      > **2.11.1 状态（2026-09-01）**：GitHub Release v2.11.1 已发布（tag `v2.11.1`，CI 自动生成
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt`，`:!harness` 剔除 harness）；npm
      > `iterate-skill-installer@2.11.1` 已发布（`npm view` 确认 latest=2.11.1）；ClawHub
      > （skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本 `.dist_tmp/clawhub_publish.py`
      > + `clawhub-stage-2.11.1`（76 文件归档，发布 71 文件）发布 2.11.1（响应 `ok:true`、
      > `status=pending`，versionId `k97476thb57248qjvwbn8z3k2n8djtxf`，发布前 resolve 显示
      > `latestVersion: 2.11.0`，发布后待传播为 2.11.1）；ModelScope 已 PATCH 生效
      > （`.dist_tmp/rebuild_ms_2111.py` 重建 2.11.1 精简 zip 426,568 字节、69 文件，
      > `update_skill_settings` success，file_id `fb0050a8-8f39-4d6c-9456-6a7070732412`）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，65 文件、424,236 字节，
      > versionId `280724`，`tags.latest=2.11.1`，`reviewStatus/securityScanStatus/contentAuditStatus=
      > pending` 为平台异步审核）。
      > 2.11.1 核心变更：偏门范围 on-the-fly 重定义「禁抄预设」——未命中命名维度集的 goal 必须
      > 从根（维度全集）重新推导方案，禁止以全局 `dimensions`/任一维度集为起点筛选微调，每个选中
      > 维度须给出本范围特有的独立理由；`scripts/validate.py decisions` 新增对重定义记录小节的机器校验
      > （要求 `Origin scope:` 与 `Independent reason` 表格、理由不得照抄 `config/dimensions/<dim>.yaml`
      > 默认 focus）；决策日志模板同步新增该小节。发版前已全量通过 pytest（862 个）+ ruff。
      > **2.11.0 状态（2026-09-01）**：GitHub Release v2.11.0 已发布（tag `v2.11.0`，CI 自动生成
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt` + `iterate-qoder.zip`，`:!harness` 剔除 harness）；
      > npm `iterate-skill-installer@2.11.0` 已发布（`npm view` 确认 latest=2.11.0）；ClawHub
      > （skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本 `.dist_tmp/clawhub_publish.py`
      > + `clawhub-stage-2.11.0`（76 文件归档，发布 71 文件）发布 2.11.0（响应 `ok:true`、
      > `status=pending`，versionId `k9791qfc8epsvq8hcsvk85fan18dk7c5`，resolve 确认
      > `latestVersion: 2.11.0` 已传播）；ModelScope 已 PATCH 生效（`rebuild_ms_2110.py`
      > 重建 2.11.0 精简 zip 421,804 字节、69 文件，`update_skill_settings` success，
      > file_id `d320aafb-16a4-4dd1-8a3d-d66d27586ff1`，`get_skill.last_modified` 已更新至当日）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，65 文件、
      > 409.6 KB，versionId `280650`，`tags.latest=2.11.0`，`reviewStatus/securityScanStatus/
      > contentAuditStatus=pending` 为平台异步审核）。
      > 本次发版核心变更：审查维度集（dimension_sets）、增量刷新（refresh 保留用户编辑区）、
      > `iterate config` 非交互式配置子命令，发版前已全量通过 pytest + ruff + mypy。
      > **2.10.0 状态（2026-08-30）**：GitHub Release v2.10.0 已发布（tag `v2.10.0`，CI 自动生成
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt` + `iterate-qoder.zip`，`:!harness` 剔除 harness）；
      > npm `iterate-skill-installer@2.10.0` 已发布（`npm view` 确认 latest=2.10.0）；ClawHub
      > （skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本 `.dist_tmp/clawhub_publish.py`
      > + `clawhub-stage-2.10.0` 发布 2.10.0（69 文件，响应 `ok:true`、`status=pending`，
      > versionId `k970tndrg02jpb4320bym5hgns8df38h`，`latestVersion` 数分钟传播）；ModelScope
      > 已 PATCH 生效（`rebuild_ms_2100.py` 重建 2.10.0 精简 zip 411,499 字节，
      > `update_skill_settings` success，file_id `dd25d77d-20b4-4c88-9be8-77a12fef3c76`）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，63 文件，
      > versionId `277355`，`tags.latest=2.10.0`，`reviewStatus/securityScanStatus/pending`
      > 为平台异步审核）。发版时清理了被误提交的本地 `.trae-html-share-packages` 工具残留
      > （已 git rm + 加入 `.gitignore`，修正常涉及发布包的 stage/zip 均复核为 0）。
      > **2.9.1 状态（2026-08-27）**：GitHub Release v2.9.1 已发布（tag `v2.9.1`，CI 自动生成
      > `iterate-skill.tar.gz` 379,201 字节 + `SHA256SUMS.txt`，`:!harness` 剔除 harness，release
      > workflow 自动上传）；npm `iterate-skill-installer@2.9.1` 已发布（`npm view` 确认
      > latest=2.9.1）；ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本
      > `.dist_tmp/clawhub_publish.py` + `clawhub-stage-2.9.1` 发布 2.9.1；ModelScope 已 PATCH
      > 生效（2.9.1 精简 zip 408,767 字节，`update_skill_settings` success，skill_file 指向 2.9.1
      > 精简包）；SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，versionId
      > `271762`，`tags.latest=2.9.1`，`reviewStatus/securityScanStatus=pending` 为平台异步审核）。
      > **2.9.0 状态（2026-08-26）**：GitHub Release v2.9.0 已发布（tag `v2.9.0`，CI 自动生成
      > `iterate-skill.tar.gz` 363,078 字节 + `SHA256SUMS.txt`，`:!harness` 剔除 harness，release
      > workflow success 10s）；npm `iterate-skill-installer@2.9.0` 已发布；ClawHub（skillId
      > `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本 `.dist_tmp/clawhub_publish.py` 发布 2.9.0
      > （65 文件，响应 `ok:true`、`status=pending`，versionId `k9729hvta6v07r899exy2wesv58d4ve9`，
      > `latestVersion` 数分钟传播，待复查）；ModelScope 已 PATCH 生效（上传 2.9.0 精简 zip
      > 383 KB，file_id `261d5466-31a1-4966-a349-0153637beea2`，`update_skill_settings` success）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，versionId `269836`，
      > `tags.latest=2.9.0`，`reviewStatus/securityScanStatus/pending` 为平台异步审核）。
      > **2.8.1 状态（2026-08-23）**：GitHub Release v2.8.1 已发布（tag `v2.8.1`，CI 自动生成
      > `iterate-skill.tar.gz` 358,948 字节 + `SHA256SUMS.txt`，`:!harness` 剔除 harness，release
      > workflow success 12s）；npm `iterate-skill-installer@2.8.1` 已发布；ClawHub（skillId
      > `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本 `.dist_tmp/clawhub_publish.py` 发布 2.8.1
      > （65 文件，响应 `ok:true`、`status=pending`，versionId `k973ymjma5q386kq4dhz3kzvg98d0d3c`，
      > `latestVersion` 数分钟传播，待复查）；ModelScope 已 PATCH 生效（上传 2.8.1 精简 zip
      > 379 KB，file_id `6eba7c0a-8c26-4d9a-960a-d92b2993d113`，`update_skill_settings` success）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，versionId `263704`，
      > `tags.latest=2.8.1`，`reviewStatus/securityScanStatus/pending` 为平台异步审核）。
      > **2.8.0 状态（2026-08-22）**：GitHub Release v2.8.0 已发布（tag `v2.8.0`，CI 自动生成
      > `iterate-skill.tar.gz` + `SHA256SUMS.txt`，`:!harness` 剔除 harness）；npm
      > `iterate-skill-installer@2.8.0` 已发布（发布时因沙箱 PATH 无 node，npm 走
      > `/usr/local/bin/node /usr/local/lib/node_modules/npm/bin/npm-cli.js` 调用）；
      > ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本
      > `.dist_tmp/clawhub_publish.py` 发布 2.8.0（65 文件，响应 `ok:true`、
      > `status=pending`，versionId `k979c16gb6em97h0vf6p5bff118cy5vt`，`latestVersion`
      > 需数分钟传播）；ModelScope 已 PATCH 生效（`verify_update_280.py` 上传 2.8.0
      > 精简 zip 382,483 字节，file_id `f1d44ec0-53b7-4103-9a28-436c58f841fb`，
      > `update_skill_settings` success）；SkillHub（skillId `104490`）`skillhub publish`
      > 成功（`ok:true`，versionId `262149`，`tags.latest=2.8.0`，`reviewStatus/
      > securityScanStatus=pending` 为平台异步审核）。
      > **2.6.0 状态（2026-08-21）**：GitHub Release v2.6.0 已发布，CI 已上传
      > `iterate-skill.tar.gz`（346,530 字节）+ `SHA256SUMS.txt`（github-actions[bot] 上传，
      > release `published_at` 2026-08-21T14:35:49Z）；npm `iterate-skill-installer@2.6.0`
      > 已发布；ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）经并发脚本
      > `.dist_tmp/clawhub_publish.py` 提交 2.6.0，发布响应 `status=pending`（平台异步，
      > `latestVersion` 需数分钟传播，待复查确认）；ModelScope 已 PATCH 生效（`verify_update.py`
      > 上传 2.6.0 精简 zip 并 `update_skill_settings` 成功，skill_file 指向 2.6.0 精简包）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，versionId `260224`，
      > `tags.latest=2.6.0`，`reviewStatus/securityScanStatus=pending` 为平台异步审核）。
      > **SkillHub 新增坑**：专用包除剔除 LICENSE 外还要剔除 `.gitignore` `.gitmodules`
      > 等一切点文件/无扩展名文件（服务端 400「不允许的文件类型」），`rebuild_skillhub.py`
      > 已改为通用黑名单 `_banned()`（basename 小写命中黑名单、以 `.` 开头或无扩展名即剔除）。
      > **2.5.0 状态（2026-08-21）**：ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）
      > 经并发脚本 `.dist_tmp/clawhub_publish.py` 上传并发布 `latestVersion: 2.5.0` 已生效；ModelScope
      > 已 PATCH 生效（`verify_update.py` 上传精简 zip 并 `update_skill_settings` 成功，
      > skill_file 指向 2.5.0 精简包）；SkillHub（skillId `104490`）`skillhub publish` 成功
      > （`ok:true`，versionId 255314，`tags.latest=2.5.0`，`reviewStatus/securityScanStatus=pending`
      > 为平台异步审核）。三平台一致。
      > **2.4.5 状态（2026-08-21）**：ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）
      > `latestVersion: 2.4.5` 已生效（发布响应 `ok:true`，versionId `k97agect6q7q0a38zy4p1hhgkd8cxzm6`，
      > 初始 `status=pending`，约数分钟后 latestVersion 传播为 2.4.5）；ModelScope 已 PATCH 生效
      > （file_id `0c4c8bee-57d5-4810-aca4-0597bf5b808b`，`success:True`，skill_file 指向 2.4.5 精简包 325.4KB）；
      > SkillHub（skillId `104490`）`skillhub publish` 成功（`ok:true`，versionId 254717，`tags.latest=2.4.5`，
      > `reviewStatus/securityScanStatus=pending` 为平台异步审核）。三平台一致。
      > **2.4.0 状态（2026-08-19）**：ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）
      > `latestVersion: 2.4.0` 已生效；ModelScope 已 PATCH 生效（file_id `5a322066…`，
      > skill_file 指向 2.4.0 精简包 305.8KB）；SkillHub（skillId `104490`）`skillhub publish`
      > 成功（`ok:true`，versionId 246530，`tags.latest=2.4.0`）。三平台一致。
      > **2.3.20 状态（2026-08-19）**：ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）
      > `latestVersion` 已激活为 2.3.20；ModelScope 已 PATCH 生效（file_id 593dcf19…，
      > skill_file 指向 2.3.20 精简包）；SkillHub（skillId `104490`）`skillhub publish` 成功
      > （`ok:true`，versionId 246436，`tags.latest=2.3.20`），公开 `latestVersion` 指标仍有
      > 平台传播延迟，待复查确认。
      > **2.3.18 状态（2026-08-18）**：ModelScope 已生效（`update_skill_settings` PATCH 成功，
      > skill_file 指向 2.3.18 精简包）；ClawHub（skillId `kd73s950z2gathsjtaenp987cx8ax0mm`）
      > 与 SkillHub（skillId `104490`）均已 HTTP 200 提交 2.3.18，发布响应 `status=pending`，
      > 其 `latestVersion` 仍显示 2.3.17，属平台异步审核/传播延迟，需复查确认后再勾选。

---

## 项目 2：iterate-harness（Python 引擎 + npm 包装器）

### 版本锁步规则

`npm 包装器 version == harness 版本 == GitHub tag`（npm `1.9.1` → tag `v1.9.1`）。
包装器首次运行会把匹配版本的 release tarball pip 安装进托管 venv，npm 升级后
stamp 不匹配会自动重装到新 tag。

### 需要同步的版本号文件

| 文件 | 字段 |
|---|---|
| `harness/iterate-harness/pyproject.toml` | `[project].version` |
| `harness/iterate-harness/src/iterate_harness/__init__.py` | `__version__`（若存在） |
| `harness/iterate-harness/npm/package.json` | `version` |
| `harness/iterate-harness/CHANGELOG.md` | 新增版本条目 |

### 发布清单

- [ ] **1. 同步版本号**：编辑上述文件 + 更新 `CHANGELOG.md`（保留旧条目）。
- [ ] **2. 本地验证**：跑通 harness 测试（`cd harness/iterate-harness && pytest tests/ -q`）
      与 npm 包装器测试（`cd harness/iterate-harness/npm && node --test test/bootstrap.test.js`）。
- [ ] **3. 提交并推送主仓库**：`git commit && git push origin main`。
- [ ] **4. subtree 拆分到独立发布仓**：
      ```bash
      git subtree split --prefix=harness/iterate-harness -b subtree-harness
      git push harness-origin subtree-harness:main
      git branch -D subtree-harness
      ```
      > 独立仓 `jingzhao-l/iterate-harness` 同时承载 Python 源码 + `npm/` 包装器。
- [ ] **5. 独立仓打 tag + Release**：在独立仓打 `v<X.Y.Z>` tag 并创建 GitHub Release
      （作为 npm 包装器 pip-install 的 tarball 锚点）。
- [ ] **6. 同步发布工作区 + npm publish**：
      ```bash
      # 进入发布工作区（克隆的独立仓，gitignore）
      cd .release/iterate-harness
      git pull origin main
      cd npm
      npm publish
      ```
      验证：`npm install -g iterate-harness && ih --version` 输出新版本。
      > npm `repository` 元数据指向独立仓 `jingzhao-l/iterate-harness`。
      >
      > **1.16.2 发布记录（2026-08-28）**：版本号在 `__init__.py` / `npm/package.json` / `CHANGELOG.md`
      > 同步至 1.16.2；校验 1995 pytest + 39 npm 包装器测试全过。**subtree split push 被拒
      > （non-fast-forward）**：独立仓 main 因官方 dependabot merge 提交（`a136035` 等）与
      > `git subtree split` 产物历史产生分歧，改用替代路径在 `.release/iterate-harness` 工作区
      > （与公开 main 共享历史）提交并快进推送（`90ff6bb..140ae27`）。GitHub Release v1.16.2 已建，
      > release.yml 构建 `iterate_harness-1.16.2-py3-none-any.whl` 上传 release 并自动发布 PyPI 1.16.2
      >（已验证 PyPI latest=1.16.2）；npm `iterate-harness@1.16.2` 已发布（registry 传播约 60s）。
      > 纯自动后台升级 + `reasoning_effort` + 图片/视觉附件透传三项特性随本版上线。
      >
      > **1.16.3 发布记录（2026-08-31）**：mypy strict 全量归零（修复 40+ 模块严格类型错误）+
      > CI 新增 `mypy src` 门禁 + WebUI 路径环逃逸防护（`os.path.realpath(strict=True)`）+
      > WebUI 选择菜单契约修正。继续走 `.release/iterate-harness` 替代路径（与公开 main 共享
      > 历史）提交并快进推送（`a9251d9..597a436`）。GitHub Release v1.16.3 已建，release.yml
      > 构建 `iterate_harness-1.16.3-py3-none-any.whl` 上传 release + 自动发布 PyPI 1.16.3
      >（已验证 PyPI latest=1.16.3）；npm `iterate-harness@1.16.3` 已发布（registry 传播约 60s），
      > npm 包装器 `ih --version` 验证 =1.16.3。

---

## 项目 3：iterate-plugin（dsh 插件）

### 版本规则

**独立版本线**（自 2.3.7 起），不再与 skill 本体版本号强绑定。仅改
`harness/iterate-plugin/package.json` 的 `version`。

### 需要同步的版本号文件

| 文件 | 字段 |
|---|---|
| `harness/iterate-plugin/package.json` | `version` |
| `harness/iterate-plugin/package-lock.json` | `version` |
| `harness/iterate-plugin/CHANGELOG.md`（若存在） | 新增版本条目 |

### 发布清单

- [ ] **1. 同步版本号**：编辑 `package.json`（含 `package-lock.json` 若已提交）。
- [ ] **2. 本地验证**：`cd harness/iterate-plugin && npm install && npm run typecheck && npm test`。
- [ ] **3. 提交并推送主仓库**：`git commit && git push origin main`。
- [ ] **4. subtree 拆分到独立发布仓**：
      ```bash
      # 若尚未配置 plugin 独立仓 remote（主仓库默认只有 origin / harness-origin）：
      git remote add plugin-origin https://github.com/jingzhao-l/iterate-plugin.git

      git subtree split --prefix=harness/iterate-plugin -b subtree-plugin
      git push plugin-origin subtree-plugin:main
      git branch -D subtree-plugin
      ```
      > 独立仓 `jingzhao-l/iterate-plugin` 带 `dsh-plugin` topic，作为 dsh 生态发现入口。
      >
      > **⚠️ 非快进/无关联历史坑（2026-08-23 · 2.12.1）**：若 `git push plugin-origin subtree-plugin:main`
      > 被拒（non-fast-forward），且 `git merge-base plugin-origin/main subtree-plugin` 为空
      > （两者历史不相关），说明公开仓 main 是被早期 `git subtree push`（含 merge commit）建起的
      > 独立历史，与当前 `git subtree split` 产物无公共祖先。不要 `--force`、不要裸 `git merge`
      > （会“refusing to merge unrelated histories”）。**可用的替代路径**：直接改在 `.release/iterate-plugin`
      > 工作区（它与公开仓 main 共享历史）提交并快进推送：
      > ```bash
      > cd .release/iterate-plugin && git pull origin main        # 对齐公开仓 main
      > # 从主仓库把插件目录同步过来（排除 node_modules/.git）：
      > rsync -a --exclude node_modules --exclude .git --exclude .release \
      >   /Volumes/Eng-Dev/iterate-skill/harness/iterate-plugin/ ./
      > git status --short      # 应只出现本次变更文件，再按需 git add 指定文件
      > git commit && git push origin main
      > ```
      > 之后照常 `.release/iterate-plugin` 里 `npm publish`。
      > **2.12.1 发布记录（2026-08-23）**：分支 `release/plugin-2.12.1`（基于 origin/main，
      > cherry-pick 两笔 client fix），版本 2.12.0→2.12.1；公开仓 main `649a146..8b2b7d0`；
      > npm `iterate-plugin@2.12.1` latest 已生效（62 文件 / 241.4 kB）。
      > **2.12.3 发布记录（2026-09-01）**：走 `.release/iterate-plugin` 替代路径（与公开仓
      > main 共享历史）发布 2.12.3。变更：适配 dsh `0.1.2-alpha.3`（JsonValue 迁至
      > `@deepseek-ai/dsh-util-values`）、修复 git-scope 非 ASCII 文件名 UTF-8/octal 解码、
      > 观测台 UX（live/timeline 筛选、线程全部展开/收起、JSON 导出、运行阶段 chip）并补齐
      > 426 个单元测试；独立仓 main `3377f91..0e745f9`（含重建 dist/jobs.js 与 client bundle，
      > 修复 git-clone 安装 dist 与 src 不一致问题）；npm `iterate-plugin@2.12.3` latest
      > 已生效（64 文件 / 254.0 kB）。
- [ ] **5. 同步发布工作区 + npm publish**：
      ```bash
      cd .release/iterate-plugin
      git pull origin main
      npm publish
      ```
      验证：npm 上 `iterate-plugin` 版本为 `<X.Y.Z>`。
      > npm `repository` 元数据指向主仓库 `jingzhao-l/iterate-skill`（目录 `harness/iterate-plugin`）。

---

## 常见遗漏点（Checklist 之外）

- **skill 侧**：改了代码但忘记同步 `npm-installer/package.json` 版本 → npx 拉到旧版安装器。
- **skill 侧**：ClawHub 发布未传 `--name Iterate` → 显示名变成目录名。
- **skill 侧**：ModelScope 用完整 zip → 超 5MiB 失败；SkillHub 忘了去掉 LICENSE → `Broken pipe`。
- **harness 侧**：npm 包装器版本与 harness/tag 不同步 → 用户升级后装错版本。
- **harness 侧**：subtree 拆分后忘记在独立仓打 tag → npm 包装器 pip-install 找不到 tarball。
- **plugin / harness 侧**：subtree push 后忘记同步 `.release/` 工作区就直接 `npm publish`
  → 发布会发布旧版本。

---

## 快速对照（命令速查）

| 动作 | 命令 |
|---|---|
| skill 打 tag | `git tag v<X.Y.Z> && git push origin v<X.Y.Z>` |
| skill npm 安装器 | `cd npm-installer && npm publish` |
| skill ClawHub | `clawhub publish <stage> --slug iterate-skill --name Iterate --version <X.Y.Z> --no-input` |
| skill ModelScope | `openapi.update_skill_settings(owner, name, {'skill_file': file_id})`（精简 zip <5MiB） |
| skill SkillHub | 上传 `iterate-skill-skillhub.zip`（去 LICENSE），skillId `104490` |
| harness subtree | `git subtree split --prefix=harness/iterate-harness -b subtree-harness && git push harness-origin subtree-harness:main` |
| harness npm | `cd .release/iterate-harness/npm && npm publish`（先 `git pull`） |
| plugin subtree | `git subtree split --prefix=harness/iterate-plugin -b subtree-plugin && git push plugin-origin subtree-plugin:main`（先 `git remote add plugin-origin https://github.com/jingzhao-l/iterate-plugin.git` 若未配置） |
| plugin npm | `cd .release/iterate-plugin && npm publish`（先 `git pull`） |