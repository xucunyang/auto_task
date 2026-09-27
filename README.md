# Auto Task - 任务自动化系统

> **稳定性优先的 LLM Agent 任务编排框架**  
> 文件/DB 为唯一事实源，调度器独立于 Agent，所有状态可恢复、可幂等、可校验。

---

## 📁 项目结构

```text
├── orchestrator/        # 主编排器及子组件
│   ├── config/          # 调度配置 (schedule.yaml)
│   ├── event/           # 事件管理
│   ├── subagent/        # 子 Agent 执行器
│   ├── verifier.py      # 验证器
│   └── notifier.py      # 通知器
├── state/               # 状态存储
│   ├── master.json      # 主状态文件 (DAG + 任务索引)
│   ├── tasks/           # 任务分片 (每个任务独立状态)
│   └── events/          # 事件日志 (追加式 JSONL)
├── schemas/             # 验收标准 schema
├── templates/           # 计划模板
├── tests/               # 测试用例
├── logs/                # 运行日志
├── config/              # 配置文件
└── artifacts/           # 任务产物 (可选)
```

---

## 🎯 核心原则

1. **聊天上下文不是状态存储**  
   Agent 可以忘，但文件/DB 不能忘。每次执行前从磁盘恢复状态。

2. **调度器必须是确定性程序**  
   定时定点由 cron / APScheduler 负责，Agent 只被触发执行。

3. **主 Agent 不执行长任务**  
   只做拆分、派发、校验、推进，避免上下文被具体任务占满。

4. **子 Agent 无状态执行**  
   每个子任务独立上下文，执行完销毁，不依赖历史对话。

5. **所有写操作原子化、幂等化、带锁**  
   防止重复执行、并发写坏文件、崩溃后状态不一致。

6. **任务分片是事实源**  
   子 Agent 只更新自己的任务分片，主 Agent 校验后刷新主文件。

---

## 🏗️ 总体架构

```
┌─────────────┐
│ Scheduler   │ 定时触发 (每天固定时间)
└──────┬──────┘
       ↓ 生成/触发计划
┌─────────────┐
│ Master      │ 读取 master + task 分片
│ Agent        │
│ Orchestrator│
└──────┬──────┘
       ↓ 拆分 DAG 并派发
┌─────────────┐
│ Sub Agent   │ 执行任务、自测、写结果
│ Executor     │
└──────┬──────┘
       ↓ 验证通过 → DONE，失败 → RETRY/FAILED
┌─────────────┐
│ Verifier    │ 独立验收 + 业务规则校验
└─────────────┘
```

---

## 📊 任务状态机

```text
PENDING → READY → RUNNING → SUBMITTED → VERIFYING → DONE
                         ↓            ↓
                      FAILED       RETRY → READY
                         ↓
                    DEAD_LETTER
```

**补充状态：**
- `BLOCKED`：依赖未完成
- `WAITING_APPROVAL`：需要人工审批
- `CANCELLED`：取消
- `SKIPPED`：跳过
- `DONE`：终态，不可再执行

---

## 🎭 角色职责

| 角色 | 职责 |
|------|------|
| **Scheduler** | 每天固定时间触发，生成计划实例，支持 cron/时区/错过补跑 |
| **Master Agent** | 读取 master、拆分 DAG、派发任务、校验状态、推进下游 |
| **Sub Agent** | 读任务卡、执行、自测、写结果和分片、写交接摘要 |
| **Verifier** | 独立验收，执行测试和业务规则 |
| **Notifier** | 告警、日报、人工介入通知 |

---

## 📁 文件协议

### master.json - 主状态文件

```json
{
  "plan_id": "daily_report_2026-09-27",
  "timezone": "Asia/Shanghai",
  "status": "RUNNING",
  "version": 13,
  "created_at": "2026-09-27T08:05:00+08:00",
  "updated_at": "2026-09-27T08:30:00+08:00",
  "tasks": [
    {
      "id": "t1_collect",
      "name": "采集数据",
      "status": "DONE",
      "depends_on": [],
      "shard": "state/tasks/t1_collect.json"
    },
    {
      "id": "t2_clean",
      "name": "清洗数据",
      "status": "READY",
      "depends_on": ["t1_collect"],
      "shard": "state/tasks/t2_clean.json"
    }
  ]
}
```

### 任务分片示例

```json
{
  "task_id": "t2_clean",
  "plan_id": "daily_report_2026-09-27",
  "status": "RUNNING",
  "owner": "sub-agent-3",
  "lease_until": "2026-09-27T08:35:00+08:00",
  "objective": "清洗采集数据，输出 clean.csv",
  "acceptance": [
    {
      "type": "command",
      "cmd": "python tests/test_clean.py",
      "expect_exit": 0
    }
  ]
}
```

---

## 🔧 快速启动

### 1. 配置调度器

编辑 `config/schedule.yaml`：

```yaml
jobs:
  - id: daily_report
    cron: "0 8 * * *"              # 每天 8 点执行
    timezone: Asia/Shanghai
    template: templates/daily_plan.yaml
    misfire_grace_time: 3600       # 错过 1 小时内补跑
    concurrency: 1                  # 限制并发
```

### 2. 运行编排器

```bash
python orchestrator/orchestrator.py
```

### 3. 手动执行单个任务

```bash
python orchestrator/subagent_executor.py t1_collect
```

---

## 🧪 测试与校验

验收标准分层设计：

```yaml
acceptance:
  - type: command          # 运行测试命令
    cmd: pytest tests/test_clean.py
    expect_exit: 0
  - type: file_exists      # 检查产物存在
    path: artifacts/clean.csv
  - type: json_schema      # Schema 校验
    path: artifacts/summary.json
    schema: schemas/summary.json
  - type: business_rule    # 业务规则
    expr: "rows > 0 && null_rate < 0.01"
```

---

## 🛡️ 稳定性保障

| 机制 | 说明 |
|------|------|
| **原子写** | 写临时文件 → fsync → rename |
| **任务锁** | filelock / flock / Redis 锁 |
| **乐观锁** | 任务分片带 version，更新时比对 |
| **幂等键** | idempotency_key，重复触发不重复执行 |
| **租约机制** | lease_until，过期自动回收 |
| **重试策略** | 指数退避 + 最大次数 → 死信队列 |
| **事件日志** | 所有状态变更可追溯 (JSONL) |

---

## 📈 生产部署建议

**轻量版：**
- 状态：SQLite + JSON 文件
- 调度：APScheduler / cron
- 锁：filelock / SQLite 事务

**生产版：**
- 状态：PostgreSQL
- 调度：Temporal / Airflow / K8s CronJob
- 队列：Redis Stream / RabbitMQ
- 监控：Prometheus + Grafana

---

## 📝 TODO - 电梯加装政策调研任务

**业务目标：** 生成《各地电梯加装政策调研报告》

**进度：** 12/12 任务已完成 ✓

**当前状态：** 所有架构组件就绪，等待手动触发执行

**执行命令：**
```bash
python orchestrator/subagent_executor.py t1_collect
python orchestrator/subagent_executor.py t2_clean
# ... 其他任务
```

---

## 📚 核心文档

- [task.md](./task.md) - 架构设计详细说明
- [todo.md](./todo.md) - 当前任务清单
- [session_summary.md](./session_summary.md) - 会话摘要
- [current_state.md](./current_state.md) - 当前运行状态

---

## 🎯 项目理念

> **Agent 可以失忆，但任务状态不能丢。**

本系统保证：
- ✅ 每天固定任务定时定点执行
- ✅ 长时间任务可中断、可恢复
- ✅ 上下文占满后不依赖模型记忆
- ✅ 子任务完成后状态明确
- ✅ 主 Agent 始终把控全局流程
- ✅ 测试和校验闭环
- ✅ 工程上稳定、可观测、可扩展

---

**🤖 Generated with [Claude Code](https://claude.com/claude-code)**
