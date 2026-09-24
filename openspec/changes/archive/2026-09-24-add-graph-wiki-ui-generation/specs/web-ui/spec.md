# web-ui Specification（delta）

## ADDED Requirements

### Requirement: 图谱与 wiki 视图提供生成入口

图谱视图与 wiki 视图 SHALL 在只读阅读之外提供触发生成的界面入口：图谱未构建时
SHALL 展示「构建图谱」入口，已构建时 SHALL 提供「更新图谱」入口；wiki 未生成时
SHALL 展示「生成 wiki」入口，已生成时 SHALL 提供「重新生成 wiki」入口。全部入口
SHALL 经既有生成端点（`POST /api/graph`、`POST /api/wiki`）触发并沿用其默认幂等
路径；生成期间 SHALL 禁用入口并展示进行中文案；成功后 SHALL 刷新对应视图数据；
失败 SHALL 展示后端中文 message 并保留可重试入口。wiki 生成遇图谱产物缺失时
SHALL 就地提供「构建图谱」引导，构建成功后 SHALL 自动续跑生成。CLI 路径 SHALL
保持不变且与界面入口等价。

#### Scenario: 图谱空态构建

- **GIVEN** 图谱尚未构建（读取面返回 `graph_missing`）
- **WHEN** 用户点击「构建图谱」
- **THEN** 界面经 `POST /api/graph` 触发构建，展示进行中文案并禁用按钮，成功后
  自动加载统计与画布

#### Scenario: wiki 空态生成与图谱缺失引导

- **GIVEN** wiki 尚未生成且图谱产物缺失
- **WHEN** 用户点击「生成 wiki」
- **THEN** 界面展示需先构建图谱的中文说明与「构建图谱」入口；构建成功后自动
  续跑 wiki 生成并刷新条目清单

#### Scenario: 已建态更新与重新生成

- **GIVEN** 图谱与 wiki 均已生成
- **WHEN** 用户分别点击「更新图谱」与「重新生成 wiki」
- **THEN** 界面经既有生成端点触发（未变语料命中缓存，零 LLM 调用），完成后刷新
  统计、画布与条目清单，且旧选中条目不再与新清单同屏

#### Scenario: 生成失败反馈

- **GIVEN** LLM 通道未配置或生成中途失败
- **WHEN** 生成请求返回错误
- **THEN** 界面在视图内展示后端中文 message，按钮恢复可用，当前视图状态不丢失
