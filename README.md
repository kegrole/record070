# mergecsv

mergecsv 使用 Python 标准库合并多份带有不同 CSV 方言、表头别名和数字写法的订单文件。项目不依赖任何第三方包。

## 运行

    python -m mergecsv.cli --dir demo/sources --aliases demo/aliases.json --out out/report.json

命令会生成 JSON 报告，并在 stdout 打印一行摘要，内容包含合并行数、冲突数、类型错误数、别名冲突数和来源数。

测试：

    python -m unittest test_mergecsv -v

## 配置格式

配置文件是 UTF-8 JSON，顶层包含 sources 与 columns 两个对象。

sources 的键是来源名，每个来源对应 sources/<来源名>.csv。来源方言字段如下：

- delimiter：单字符 CSV 分隔符。
- escape：引号内转义方式，只能是 doubling 或 backslash。
- nulls：空值写法列表。字段去掉首尾空白后等于其中任意字符串，即视为空值。
- encoding：Python 编解码器名称。utf-8-sig 会消费文件头 BOM；使用 utf-8 且文件带 BOM 时，解析器会显式剥离开头的 U+FEFF。

columns 的键是统一列名，必须包含 order_id。每个统一列包含：

- type：text、money 或 rate。
- aliases：该统一列允许出现的原始表头或配置别名。
- primary：冲突取值时优先使用的来源名。

## CSV 方言

解析器逐字符处理，不使用 csv 模块，以便严格区分两种转义方言。

- LF 与 CRLF 都识别为行尾。
- 双引号中的分隔符和换行保留为字段内容。
- doubling：引号内两个连续双引号解析成一个双引号。
- backslash：只在引号内识别反斜杠转义；反斜杠加下一字符得到下一字符，因此两个反斜杠得到一个反斜杠。引号外的反斜杠是普通字符。
- 编码后的开头 U+FEFF 会从整个文本开头剥离，避免影响首个表头。

## 表头与别名归一

原始表头和配置别名使用同一规则归一后再比较：

1. 剥离开头的 U+FEFF。
2. 去掉首尾空白；空白包括空格、制表符、换行、回车、不换行空格 U+00A0 和全角空格 U+3000。
3. 将下划线 _ 与连字符 - 换成空格。
4. 把连续空白压缩成一个空格。
5. 转成小写。

同一来源中，如果两个不同原始列名归一后都匹配同一个统一列，该统一列在此来源整体作废。除第一个匹配列外的其余原始表头会写入 alias_conflicts；该来源不会出现在这个统一列的 matched_sources 中。

## 数字读数

money 与 rate 共用同一套读数规则，内部使用 decimal.Decimal，不使用二进制浮点数。

1. 去掉首尾空白。
2. 如果 rate 值以 % 结尾，去掉 %，读数后除以 100。
3. 删除货币符号和货币代码：$、€、£、¥、￥、USD、EUR、GBP、CNY、RMB；货币代码大小写不敏感。
4. 整体被圆括号包住时为负数；否则末尾减号也表示负数，减号本身不参与数字解析。
5. 剩余部分只能包含数字、逗号和点。
6. 逗号和点都出现时，最后出现的是小数分隔符，另一个是千分位。
7. 只出现一种分隔符且它只出现一次、后面正好是三位数字时，它是千分位；否则它是小数分隔符。
8. money 按四舍五入、半分进位保留两位小数；rate 同样按半分进位保留最多六位小数。

结果中，money 固定输出两位小数；rate 输出最多六位小数并删除末尾多余的零。无法按规则解析的非文本值按空值处理，同时记录类型错误，不影响同键、同列的其它来源取值。

## 键、取值与冲突

主键统一列是 order_id。键值只去掉首尾空白，按大小写敏感字符串比较，并保留前导零，所以 007 与 7 是不同键。

只要某来源的一行提供了可解析的主键，这个来源就会进入该行的 sources，即使该行其它列没有值。sources 与所有报告数组都按确定顺序排序，同一输入重复运行会生成逐字节一致的 JSON。

每个非主键列按以下顺序选值：

1. 优先取该列配置的 primary 来源。
2. 主来源缺列、字段缺失、字段为空或类型错误时，按来源名字典序选择第一个有值的来源。
3. 其它来源中，取值与保留值不同的每个来源各生成一条冲突；没有取值的来源不算冲突。

文本值只去掉首尾空白后比较。数值比较使用按列类型归整后的 Decimal，所以 1,234.50 与 1234.50 是同一个值。

## 报告字段

顶层字段顺序固定为：

- rows：按 order_id 字典序排列的合并行。
- conflicts：值冲突列表。
- type_errors：非文本列无法解析的原始值列表。
- alias_conflicts：同一来源内重复匹配统一列的表头列表。
- summary：计数摘要。
- aliases_used：按统一列名排序的表头匹配结果。

rows 每行正好包含：

- order_id
- price
- tax_rate
- remark
- sources

conflicts 每条正好包含 order_id、column、kept_value、kept_source、dropped_value、dropped_source。

type_errors 每条正好包含 source、order_id、column、raw。

alias_conflicts 每条正好包含 source、column、header。

summary 正好包含 rows、conflicts、type_errors、alias_conflicts、sources。

aliases_used 每项正好包含 unified、primary、matched_sources；因别名冲突作废的来源不会进入 matched_sources。
