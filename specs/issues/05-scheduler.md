# Daily Pipeline Scheduler

- **Issue**: [#5](https://github.com/alpha-99/your-knowledge/issues/5)
- **Type**: AFK
- **Blocked by**: #4

## What to build

创建每日定时调度机制，使 UTC 0:00 自动触发 `collector → analyzer → organizer` 串行流水线。

1. 创建 GitHub Actions workflow：`.github/workflows/daily-pipeline.yml`
2. 使用 `schedule` 触发器设置 UTC 0:00 每日运行
3. Workflow 步骤依次调用三个 Agent：
   - Step 1: `@collector 采集今天的 GitHub Trending`
   - Step 2: `@analyzer knowledge/raw/github-trending-{date}.json`
   - Step 3: `@organizer 整理今天已分析的原始数据`
4. 每个步骤检查前一步骤退出状态，失败则终止后续步骤
5. 支持手动触发（workflow_dispatch）以便测试和补跑

## Acceptance criteria

- [ ] `.github/workflows/daily-pipeline.yml` 存在且格式正确
- [ ] schedule 配置为 `cron: '0 0 * * *'`（UTC 0:00）
- [ ] 三个 Agent 按顺序串行执行，前置步骤失败则后续跳过
- [ ] 支持 `workflow_dispatch` 手动触发
- [ ] workflow 执行完成后，`knowledge/articles/` 中有当日归档条目
