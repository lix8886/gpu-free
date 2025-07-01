import uuid
import pynvml
import asyncio
from collections import deque
from datetime import datetime
from typing import List, Dict

from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException

from utils import AutoEmail


# --- 初始化 ---
app = FastAPI(title="GPU 订阅与监控面板")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

try:
    pynvml.nvmlInit()
    GPU_COUNT = pynvml.nvmlDeviceGetCount()
    GPU_NAMES = [
        f"{i} " + pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(i))
        for i in range(GPU_COUNT)
    ]
except pynvml.NVMLError as error:
    print(f"初始化 NVML 失败: {error}")
    GPU_COUNT = 0
    GPU_NAMES = []


# --- 数据存储 ---
# 1. 监控任务存储 (使用字典方便通过ID删除)
MONITORING_TASKS: Dict[str, Dict] = {}

# 2. 历史数据存储 (为每个GPU创建一个固定长度的队列)
HISTORY_MAX_LENGTH = 120  # 记录 120个点 (每5秒一个点，总共1小时)
UTILIZATION_HISTORY: Dict[int, deque] = {
    i: deque(maxlen=HISTORY_MAX_LENGTH) for i in range(GPU_COUNT)
}


# --- Pydantic 数据模型 ---
class GpuTaskCreate(BaseModel):
    gpu_ids: List[int]
    util_threshold: int = Field(..., gt=0, le=100)
    email: str
    alias: str


# --- 核心逻辑 ---


def get_live_gpu_stats() -> List[Dict]:
    """仅获取GPU当前的实时状态，不包含任务逻辑"""
    stats = []
    if GPU_COUNT == 0:
        return stats
    for i in range(GPU_COUNT):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
        stats.append(
            {
                "id": i,
                "name": GPU_NAMES[i],
                "gpu_utilization": utilization.gpu,
            }
        )
    return stats


async def send_email_notification_placeholder(task: Dict):
    """
    邮件通知功能的占位符。
    未来可以在这里集成真实的邮件发送服务 (如 smtplib, sendgrid 等)。
    """
    print("--------------------------------------------------")
    print(f"✔️  触发邮件通知!")
    print(f"  - 任务ID: {task['id']}")
    print(f"  - 收件人: {task['email']}")
    print(f"  - 用户名：{task['alias']}")
    print(f"  - 条件: GPUs {task['gpu_ids']} 占用率均低于 {task['util_threshold']}%")

    # 这里只是打印，未来应替换为真实邮件发送代码
    ae = AutoEmail(receiver=task["email"], mail_title="✔️  GPU触发邮件通知!")
    ae.addcontext(
        f"任务 {task['id']} 已完成\n\nGPUs {task['gpu_ids']} 占用率均低于 {task['util_threshold']}%"
    )
    ae.send(task["email"])
    print("邮件已发送。")
    print("--------------------------------------------------")


async def check_tasks_and_record_history():
    """后台常驻任务，每5秒执行一次，完成后自动删除任务"""
    while True:
        await asyncio.sleep(5)

        live_stats = get_live_gpu_stats()
        if not live_stats:
            continue

        current_time = datetime.now().strftime("%H:%M:%S")
        for stat in live_stats:
            UTILIZATION_HISTORY[stat["id"]].append(
                {"time": current_time, "util": stat["gpu_utilization"]}
            )

        # --- 核心修改 ---
        tasks_to_delete = []

        # 遍历所有任务
        for task_id, task in MONITORING_TASKS.items():
            try:
                target_gpus_stats = [
                    s for s in live_stats if s["id"] in task["gpu_ids"]
                ]

                # 确保我们获取了所有目标GPU的数据
                if len(target_gpus_stats) != len(task["gpu_ids"]):
                    continue

                # 检查是否所有目标GPU都满足空闲条件
                is_idle = all(
                    s["gpu_utilization"] < task["util_threshold"]
                    for s in target_gpus_stats
                )

                if is_idle:
                    await send_email_notification_placeholder(task)
                    print(
                        f"✔️ 任务 {task_id} ({task.get('alias', '')}) 已完成，将被删除。"
                    )
                    tasks_to_delete.append(task_id)  # 将完成的任务ID加入待删除列表

            except Exception as e:
                print(f"检查任务 {task_id} 时出错: {e}")

        # 循环结束后，统一删除所有已完成的任务
        if tasks_to_delete:
            for task_id in tasks_to_delete:
                if task_id in MONITORING_TASKS:
                    del MONITORING_TASKS[task_id]
            print(f"🗑️ 已自动删除 {len(tasks_to_delete)} 个已完成的任务。")


@app.on_event("startup")
async def startup_event():
    """在应用启动时，启动后台任务"""
    asyncio.create_task(check_tasks_and_record_history())


# --- API 端点 ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """渲染主页面，并传递GPU信息用于表单生成"""
    gpus = [{"id": i, "name": name} for i, name in enumerate(GPU_NAMES)]
    return templates.TemplateResponse("index.html", {"request": request, "gpus": gpus})


@app.get("/tasks")
async def get_tasks():
    """获取当前所有监控任务列表"""
    return JSONResponse(content=list(MONITORING_TASKS.values()))


# 在 main.py 中找到 create_task 函数并替换
@app.post("/task")
async def create_task(task_data: GpuTaskCreate):
    """创建一个新的GPU订阅任务"""
    task_id = str(uuid.uuid4())
    alias = task_data.alias.strip()
    if not alias:
        alias = task_data.email.split("@")[0]

    new_task = {
        "id": task_id,
        "gpu_ids": task_data.gpu_ids,
        "gpu_names": [GPU_NAMES[i] for i in task_data.gpu_ids],
        "util_threshold": task_data.util_threshold,
        "email": task_data.email,
        "alias": alias,
    }
    MONITORING_TASKS[task_id] = new_task
    return JSONResponse(content=new_task, status_code=201)


@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """根据ID删除一个任务"""
    if task_id in MONITORING_TASKS:
        del MONITORING_TASKS[task_id]
        return JSONResponse(content={"message": "任务已删除"})
    raise HTTPException(status_code=404, detail="未找到任务")


@app.get("/history")
async def get_history():
    """获取用于图表展示的历史数据"""
    # Convert each deque to a list before returning as JSON
    content = {
        gpu_id: list(history_deque)
        for gpu_id, history_deque in UTILIZATION_HISTORY.items()
    }
    return JSONResponse(content=content)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """通过WebSocket实时推送GPU的精简实时数据"""
    await websocket.accept()
    try:
        while True:
            # WebSocket现在只推送最核心的实时数据，用于更新顶部卡片
            live_stats = get_live_gpu_stats()
            await websocket.send_json(live_stats)
            await asyncio.sleep(1.5)  # 2秒更新一次实时卡片
    except WebSocketDisconnect:
        print("客户端断开连接")
    except Exception as e:
        print(f"WebSocket 发生错误: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8200, reload=True)
