# 股票研究与模拟交易 Agent

## 自动测试

在项目根目录、已激活虚拟环境执行 `python -m pytest -c backend/pyproject.toml`。
测试位于 `backend/tests/`，详见 [测试说明](backend/tests/README.md)。
新环境可用 `python -m pip install -r backend/requirements-dev.lock.txt` 安装运行和测试依赖。
工具参数的手工统计已迁移到 pytest；业务模型保留在 src，教学示例仍在 examples。

D02 请求校验与异步示例已加入，运行及动手练习见 [第二天说明](docs/day02.md)。

按 `stock-agent-python-development-plan.md` 分阶段完成的学习项目。
目前已安装并锁定模型 SDK，实现 D01 调用脚本；用户已完成真实调用，并验证服务过载失败路径。回答存在超出证据的内容，具体复核和用量见 `docs/day01.md`。

## 目录

- `backend/pyproject.toml`：Python 包和直接依赖声明。
- `backend/requirements.lock.txt`：当前 Python 3.11 环境安装的依赖版本快照。
- `backend/.env.example`：本地配置样例。
- `backend/src/stock_agent/`：后续可复用的 Python 代码。
- `backend/examples/`：第一次模型调用等学习示例。
- `backend/fixtures/`：按虚构或真实历史资料分别标注的练习输入。
- `docs/day01.md`：当天进度、验收与学习笔记。

## 第一步：创建虚拟环境

在终端依次执行（当前电脑检测到 Python 3.11.1）：

```bash
cd /Users/yangmeng/Desktop/interview/stock
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -c "import sys; print(sys.executable)"
```

最后应打印 `/Users/yangmeng/Desktop/interview/stock/backend/.venv/bin/python`。
虚拟环境只创建一次；新开终端时重新执行激活命令。执行 `deactivate` 可退出。

## 第二步：保存模型配置

先确认 `backend/.env` 尚不存在，再复制样例，避免覆盖已有密钥：

```bash
cp -n backend/.env.example backend/.env
```

用编辑器打开 `backend/.env`，在 `ZHIPU_API_KEY=` 后填入智谱平台的完整 API Key，
保留 `MODEL_NAME=glm-4.7-flash`。`.env` 已列入 `.gitignore`。
不要把密钥输入到终端命令或聊天中。

脚本会读取 `backend/.env`；同名终端环境变量优先。

## 第三步：准备输入

本次选择 `backend/fixtures/nvda_2026_08_earnings.txt`，使用 NVIDIA 于 2026 年 8 月发布的真实财报摘要，包含来源、报告期和分析问题。
原 `fictional_announcement.txt` 保留为可选的虚构资料模板。真实摘要标注为 historical，不标为虚构或实时行情。
## 第四步：运行模型示例

已在本机虚拟环境中安装依赖。新环境可执行 `python -m pip install -r backend/requirements.lock.txt`。
在项目根目录、已激活的虚拟环境中执行：

```bash
# 只看模型会收到的消息，不调用 API
python backend/examples/hello_model.py --preview
# 发送一次真实请求
python backend/examples/hello_model.py
# 临时使用不存在的模型，验证失败路径，不修改 .env
python backend/examples/hello_model.py --model deliberately-invalid-model
```

脚本使用智谱国内官方 SDK `ZhipuAiClient`，关闭自动重试与思考模式，输出最多 1200 token。
超时配置控制网络等待，并非严格的整个任务总时限。脚本打印正文、可获得的用量和请求阶段耗时。
非正常结束（例如长度截断）、空正文或请求错误返回非零退出码。原始异常不打印。
`--preview` 会展示全部输入，请不要在资料文件中写入密钥。

SDK 参考：https://docs.bigmodel.cn/cn/guide/develop/python/introduction

## D01 完成标准

真实模型请求可重复运行，打印分析结果、耗时和可获得的用量；至少验证一种失败路径。
能解释输入构造、请求发送、输出解析及错误处理的位置。完成情况记录在 `docs/day01.md`。
