---
name: agent-tool-usage-strategy
description: Agent缺少工具组合使用策略，导致搜索后不抓取详情、不解析内容
type: project
---

**问题: Agent 工具使用策略缺失**

**现象:**
- 搜索航班信息时只调用 web_search，未进一步用 web_fetch 获取详情
- 获取搜索摘要后直接返回，不解析为结构化数据
- 存在 agent-browser 技能但未注册对应工具

**根因:**
- 系统提示词缺少工具组合使用指导
- 没有告诉 Agent 应该在搜索后抓取详情并解析内容

**待解决:**
在系统提示词中添加工具组合使用指导：
1. web_search 后应用 web_fetch 获取详情
2. 网页内容需要解析提取结构化信息
3. 考虑注册 agent-browser 工具或添加工厂指导
