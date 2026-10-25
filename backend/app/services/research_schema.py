"""Business-driven research fields; never a list of hand-picked stock codes."""
FAMILIES = {
    '养殖': {'match':['生猪', '养殖', '畜牧'], 'topics':['生猪', '猪价', '出栏', '饲料', '能繁母猪'], 'fields':['销量与售价', '单位成本', '供给与产能', '现金流与负债']},
    '半导体': {'match':['半导体', '集成电路', '封装材料'], 'topics':['半导体', '封装', '塑封料', '电子材料', '先进封装'], 'fields':['产品收入结构', '客户验证与量产', '产能利用率', '研发与资本开支']},
    '电力': {'match':['电力', '水电', '发电'], 'topics':['水电', '来水', '电价', '电力交易', '发电量'], 'fields':['发电量与利用小时', '电价与交易结构', '来水或燃料成本', '债务成本与分红']},
    '银行': {'match':['银行'], 'topics':['银行', '净息差', '不良贷款', '存款', '信贷'], 'fields':['净息差', '资产质量', '拨备与资本', '信贷结构']},
    '保险': {'match':['保险'], 'topics':['保险', '保费', '新业务价值', '偿付能力'], 'fields':['新业务价值', '保费结构', '投资收益', '偿付能力']},
    '互联网': {'match':['互联网', '游戏', '网络广告', '云计算'], 'topics':['互联网', '游戏', '网络广告', '云计算', '平台监管'], 'fields':['分业务收入', '用户与付费', '利润与资本开支', '回购与监管']},
    '医药': {'match':['医药', '制药', '生物制品', '医疗'], 'topics':['药品', '临床试验', '药品审批', '集采', '创新药'], 'fields':['产品销售', '临床及审批进度', '研发投入', '医保及价格']},
    '消费': {'match':['食品', '饮料', '白酒', '零售'], 'topics':['消费', '食品', '零售', '渠道库存', '提价'], 'fields':['量价与产品结构', '渠道与库存', '毛利率', '经营现金流']},
    '汽车': {'match':['整车制造', '汽车制造', '汽车零部件制造', '汽车零部件生产', '汽车整车'], 'topics':['汽车', '销量', '车型', '汽车零部件'], 'fields':['销量与售价', '订单与产品周期', '单车利润', '产能与海外业务']},
    '新能源': {'match':['光伏', '锂电', '动力电池', '储能'], 'topics':['光伏', '锂电池', '储能', '碳酸锂'], 'fields':['出货量与单价', '供需与库存', '产能利用率', '技术路线与政策']},
    '资源': {'match':['煤炭', '有色', '石油', '钢铁', '采矿'], 'topics':['煤炭', '原油', '铜价', '钢材', '矿山'], 'fields':['产销量', '商品价格与成本', '资源储量', '资本开支']},
    '地产': {'match':['房地产', '物业'], 'topics':['房地产', '销售回款', '土地', '交付'], 'fields':['销售与回款', '交付与收入确认', '存货与减值', '债务与现金']},
}


def research_fields(industry, business):
    text = (industry or '') + ' ' + (business or '')
    families = [name for name, rule in FAMILIES.items() if any(word in text for word in rule['match'])]
    # Breeding companies mention food in their licensed scope; that alone does not
    # establish retail/channel inventory as their principal operating model.
    if '养殖' in families and '消费' in families and not any(word in (industry or '') for word in ['零售','饮料','食品制造']):
        families.remove('消费')
    topics = [industry] if industry else []
    fields = ['收入与归母利润', '经营现金流', '资产负债及风险', '最新公告与事件日期']
    for family in families:
        topics.extend(FAMILIES[family]['topics'])
        fields.extend(FAMILIES[family]['fields'])
    return dict(families=families, topics=list(dict.fromkeys(t for t in topics if t)),
                fields=list(dict.fromkeys(fields)),
                limitation='字段是检索任务，不是公司已披露事实；业务关系和指标值必须另有原文支持。')


# Provider field labels and units. Unknown raw fields remain in the saved source,
# rather than being assigned a guessed financial meaning by the writer.
METRICS = {
    'TOTALOPERATEREVE':('营业总收入','元'), 'PARENTNETPROFIT':('归母净利润','元'),
    'KCFJCXSYJLR':('扣非归母净利润','元'), 'TOTALOPERATEREVETZ':('营业总收入同比','%'),
    'PARENTNETPROFITTZ':('归母净利润同比','%'), 'XSMLL':('销售毛利率','%'),
    'ZCFZL':('资产负债率','%'), 'MGJYXJJE':('每股经营现金流','元/股'),
    'ROEJQ':('加权净资产收益率','%'), 'EPSJB':('基本每股收益','元/股'),
    'NEWCAPITALADER':('资本充足率','%'), 'NONPERLOAN':('不良贷款率','%'),
    'BLDKBBL':('不良贷款拨备覆盖率','%'), 'NET_INTEREST_MARGIN':('净息差','%'),
    'NBV_LIFE':('寿险新业务价值','元'), 'SOLVENCY_AR':('偿付能力充足率','%'),
    'OPERATE_INCOME':('营业收入','货币单位依CURRENCY'), 'HOLDER_PROFIT':('股东应占利润','货币单位依CURRENCY'),
    'OPERATE_INCOME_YOY':('营业收入同比','%'), 'HOLDER_PROFIT_YOY':('股东应占利润同比','%'),
    'NETCASH_OPERATE':('经营活动现金流净额','货币单位依CURRENCY'),
    'GROSS_PROFIT_RATIO':('毛利率','%'), 'DEBT_ASSET_RATIO':('资产负债率','%'),
}
