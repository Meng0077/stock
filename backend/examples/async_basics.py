"""D02：使用 sleep 模拟两个独立 I/O 查询，不访问网络。"""

import asyncio
from time import perf_counter


async def get_company_profile() -> dict:
    print("  公司查询开始（模拟等待 1 秒）")
    await asyncio.sleep(1)
    print("  公司查询完成")
    return {"company": "教学虚构公司", "data_mode": "fixture"}


async def get_announcement() -> dict:
    print("  公告查询开始（模拟等待 2 秒）")
    await asyncio.sleep(2)
    print("  公告查询完成")
    return {"text": "虚构公告：营收同比增长 10%。", "data_mode": "fixture"}


async def main() -> None:
    print("一、创建协程不等于执行函数体")
    pending = get_company_profile()
    print(f"已获得 {type(pending).__name__}；此时还没有打印“公司查询开始”。")
    print("现在 await 它：")
    await pending

    print("\n二、顺序等待：预计约 3 秒")
    started = perf_counter()
    profile = await get_company_profile()
    announcement = await get_announcement()
    sequential = perf_counter() - started
    print(f"顺序结果：{profile}, {announcement}")
    print(f"顺序耗时：{sequential:.2f} 秒")

    print("\n三、并发等待：预计约 2 秒")
    started = perf_counter()
    # gather 调度两个协程；一个等待 I/O 时，另一个可以继续。
    profile, announcement = await asyncio.gather(
        get_company_profile(), get_announcement()
    )
    concurrent = perf_counter() - started
    print(f"并发结果：{profile}, {announcement}")
    print(f"并发耗时：{concurrent:.2f} 秒")
    print("这里重叠的是等待时间，不是用多核加速计算；实际耗时会受调度影响。")


if __name__ == "__main__":
    # asyncio.run(main())
    raise SystemExit(asyncio.run(main()))
