"""D04 输出模型练习，详见 docs/day04/01_output_schema.md。

TODO：EvidenceClaim，含 text 与 evidence_ids。
TODO：ResearchOutput，含 status、facts、inferences、missing_information、data_mode。
TODO：字符串/列表约束、额外字段限制、跨字段业务规则。
当前无实现，不代表输出校验已完成。

使用 Pydantic 定义 EvidenceClaim 和 ResearchOutput：

- EvidenceClaim：text 为非空字符串；evidence_ids 为非空证据 ID 字符串列表。
- ResearchOutput：status 限定 completed / insufficient_information。
- facts：EvidenceClaim 列表，保存资料中的事实。
- inferences：EvidenceClaim 列表，保存有证据基础但仍属推断的内容。
- missing_information：非空字符串组成的列表。
- data_mode：fixture / historical / live / mixed / null；由程序根据实际引用证据核对，不能信任模型随意标记。没有引用证据时必须为 null。

所有模型拒绝额外字段，清除字符串首尾空白；注意列表元素也需要声明约束。
completed 至少有一条事实；insufficient_information 至少说明一项缺失信息，可保留已有事实。
可使用 model_validator 检查字段之间的规则，实现时查对应版本写法。
不要为必填业务字段随意设置默认值，从而把模型漏字段隐藏掉。
"""

from typing import List, Literal, Self, Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceDataMode = Literal["fixture", "historical", "live"]
RequestDataMode = Literal["fixture", "historical", "live", "mixed"]
OutputDataMode = Literal["fixture", "historical", "live", "mixed"]

class EvidenceClaim(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True
    )
    text: str = Field(min_length=1)
    evidence_ids:Annotated[List[Annotated[str, Field(min_length=1)]], Field(min_length=1)]

class ResearchOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True
    )

    status: Literal["completed", "insufficient_information"]
    facts: List[EvidenceClaim]
    inferences:  List[EvidenceClaim]
    missing_information: List[Annotated[str, Field(min_length=1)]]
    data_mode: OutputDataMode | None

    @model_validator(mode="after")
    def check_status(self) -> Self:
        if self.status == "completed" and not self.facts:
            raise ValueError("completed 至少需要一条事实")
        if self.status == "insufficient_information" and not self.missing_information:
            raise ValueError("insufficient_information 至少说明一项缺失信息，可保留已有事实")
        has_claims = bool(self.facts or self.inferences)
        if has_claims and self.data_mode is None:
            raise ValueError("引用证据时 data_mode 不能为空")
        if not has_claims and self.data_mode is not None:
            raise ValueError("没有引用证据时 data_mode 必须为 null")

        return self
