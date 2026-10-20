# 公开来源原件补充：第一轮

本报告为第一轮历史快照；第二轮已补充幽门螺杆菌等来源，累计状态及后续变化见 [第二轮报告](PUBLIC_SOURCE_COLLECTION_2026-10-14.md)。

本轮按项目当地日期 2026-10-13 标识，实际 UTC 采集时间保存在各来源的 `retrieved_at`。对现有61个登记来源补充10个原件：8份PDF（共623页）、1份DOC、1份HTML。登记来源数没有增加；总归档字节 45016479。原始文件保留发布渠道响应字节，不用整理摘要、下载错误页或转换稿冒充原件。

## 已归档清单

| 发布页与原件题名 | 格式 / 页数 | 本地归档 | 下载渠道角色 |
| :--- | :--- | :--- | :--- |
| [原发性肝癌诊疗指南（2024年版）](https://www.nhc.gov.cn/yzygj/c100068/202404/b12cab9adae7424493cd2d387f018367/files/1732871166035_91949.pdf) | PDF / 143页 | [原件](../raw/originals/SRC-NHC-ONC-2024-01-01f2f97a8b58.pdf) | issuing_authority |
| [成人肥胖食养指南（2024年版）](https://wjw.baoji.gov.cn/col2223/col2269/202403/t20240319_652418.html) | PDF / 70页 | [原件](../raw/originals/SRC-NHC-NUT-2024-01-ce7e43937883.pdf) | government_mirror |
| [中国血脂管理指南（2023年）](https://csc.cma.org.cn/art/2023/3/28/art_619_50122.html) | PDF / 35页 | [原件](../raw/originals/SRC-CMA-CARD-2023-03-a2f5059ac268.pdf) | authoring_society |
| [抗菌药物临床应用指导原则（2015年版）](https://www.nhc.gov.cn/wjw/c100175/201508/1d3a99bcc1624eee8655055dffc58dd8.shtml) | PDF / 91页 | [原件](../raw/originals/SRC-NHC-PHAR-2015-01-b8377be1edec.pdf) | government_mirror |
| [中国成人社区获得性肺炎诊断和治疗指南（2016年版）](https://seleguide.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E6%88%90%E4%BA%BA%E7%A4%BE%E5%8C%BA%E8%8E%B7%E5%BE%97%E6%80%A7%E8%82%BA%E7%82%8E%E8%AF%8A%E6%96%AD%E5%92%8C%E6%B2%BB%E7%96%97%E6%8C%87%E5%8D%97%282016%E5%B9%B4%E7%89%88%29.html) | HTML | [原件](../raw/originals/SRC-CMA-RESP-2016-02-95955f0c4e7f.html) | publisher |
| [儿童肺炎支原体肺炎诊疗指南（2023年版）](https://www.nhc.gov.cn/wjw/c100378/202302/09c825807cb44295a3ebbf17e6a1ddca.shtml) | DOC | [原件](../raw/originals/SRC-NHC-PED-2023-01-808130c60518.doc) | issuing_authority |
| [中国糖尿病防治指南（2024版）](https://diab.cma.org.cn/cn/zhinangongshi.aspx) | PDF / 124页 | [原件](../raw/originals/SRC-CDS-ENDO-2024-01-4884c911879a.pdf) | authoring_society_linked_host |
| [中国高血压防治指南（2024年修订版）](https://www.yantai.gov.cn/art/2025/7/1/art_66786_3274344.html) | PDF / 98页 | [原件](../raw/originals/SRC-CMA-CARD-2024-01-271b4db6e7ea.pdf) | government_mirror |
| [中国心力衰竭诊断和治疗指南2024](https://csc.cma.org.cn/art/2024/4/18/art_619_56220.html) | PDF / 41页 | [原件](../raw/originals/SRC-CMA-CARD-2024-02-c8fc39d0e486.pdf) | professional_society_mirror |
| [原发性骨质疏松症诊疗指南（2022）](https://www.chinagp.net/CN/10.12114/j.issn.1007-9572.2023.0121) | PDF / 21页 | [原件](../raw/originals/SRC-CMA-ENDO-2022-01-e6b9a4423ff5.pdf) | publisher_republication |

每个来源的直接下载地址、DOI（已确认时）、完整SHA-256、采集时间、版次、出版年份、转载身份与覆盖范围见 [本轮采集清单](../raw/acquisition_rounds/2026-10-13-public-round-01.json)，并同步至 [来源登记](../raw/metadata.json)。

下载渠道区分发文机构、学会、期刊与政府/学会转载，不将转载站当作原始作者。骨质疏松PDF下载入口需要发布页提供的临时token；只登记不含token的稳定入口，重新下载时应回到发布页点击PDF。

## 版本和完整性限制

- 抗菌药物附件是《抗菌药物临床应用指导原则（2015年版）》，不是2024版。来源登记的原题名“最新规范”和year=2024已校正，旧值另行保留；本轮没有判断其现行适用性。
- 糖尿病原文是《中国糖尿病防治指南（2024版）》，不含原登记题名的“2型”。指南版次为2024，期刊发表年为2025，两者分别记录。临床摘要及Wiki正文未随采集改写。
- 骨质疏松原件是《中国全科医学》2023年再刊的2022指南，21页。末页明确“其余参考文献略”，不能当作含所有参考文献的首刊版。原登记的《中华骨质疏松和骨矿盐疾病杂志》2022年版仍待补齐；本轮归档数量包含此有限覆盖的再刊件。
- 儿童支原体肺炎保留国家卫健委2023版DOC附件，没有转换为PDF冒充原件。已发现 [官方2025版附件](https://www.nhc.gov.cn/yzygj/c100068/202509/19e7145436b049a68d4ba8c2060dfa56/files/%E5%84%BF%E7%AB%A5%E8%82%BA%E7%82%8E%E6%94%AF%E5%8E%9F%E4%BD%93%E8%82%BA%E7%82%8E%E8%AF%8A%E7%96%97%E6%8C%87%E5%8D%97%EF%BC%882025%E5%B9%B4%E7%89%88%EF%BC%89.pdf)，需另立来源并对相关摘要及规则做版本差异审核；本轮未替换2023版。
- 社区获得性肺炎取得的是期刊HTML文章响应，含正文与参考文献末条336；没有取得PDF，外链图片和样式未打包，不声称图表全部离线可用。
- 高血压、心衰、肥胖食养等使用正式政府或专业学会的公开转载附件，人工来源核验仍须核对其与作者/发文机构原版的一致性。
- 公开可下载不等于获准任意再分发；本轮只记录获取事实，未完成逐文件许可审核。后续公开部署须先核对权利。

## 本轮验证

使用PDF技能逐页解析与文本提取8份PDF（623页），渲染并视觉核对8个首页题名、版次和页码；使用ego-browser取得期刊公开下载入口。原件未修订排版或重写，个别PDF存在重复字典键解析警告。DOC通过OLE签名、文件识别与textutil只读文本提取核对首尾；HTML核对题名、DOI、正文与末条参考文献。

新增旧版Word归档支持及2项回归测试：拒绝改名为DOC的HTML错误页，保留原始字节和pending审核状态。全套115项测试通过；lint通过，0断链、0孤立页、0规则来源引用问题。README统计已同步，10个归档文件SHA-256与下载暂存文件一致。

## 未完成项与后续顺序

1. 本轮未归档幽门螺杆菌2022、乳腺癌2024、结直肠癌2025的匹配全文；已得到的loading/错误响应或不同机构、不同年份、精简版本不入库。仅说明本次未取得，不能据此断言不存在公开全文。
2. 61个来源仍有51个未归档；已归档的骨质疏松和HTML外链资产另有完整性限制。教材、综合来源、药品说明书汇编需拆解为明确书目或具体制剂/企业/批准文号，不能硬配一份相近资料。
3. 人工核对这10个原件的来源、题名、版本和权利，并登记真实审核人的来源核验记录。
4. 为关键临床结论与规则补原文页码/章节定位，再由医师或药师进行专业审校。

当前来源核验仍为0/61，临床审核仍为页面0/426、规则0/108；所有整理摘要保留，`clinicalReady=false`。归档成功不代表内容已经临床认证。
