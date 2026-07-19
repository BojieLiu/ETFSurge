"""Fix: add 511880 to CANDIDATE_POOL, ensure both monetary ETFs classified as defense"""
c = open('E:/ETF_Surge/backend/app/services/strategy_design.py', 'r', encoding='utf-8').read()

# Add 511880 entry after 511090 (30年国债ETF)
old = '''    \"511090\": {\"name\": \"30年国债ETF\", \"layer\": \"defense\", \"beta\": -0.1, \"liquidity\": 10.0,
               \"reason\": \"长久期利率债，对冲权益波动\"},
    \"511990\": {\"name\": \"货币ETF\", \"layer\": \"defense\", \"beta\": 0.0, \"liquidity\": 50.0,
               \"reason\": \"现金管理工具，流动性缓冲\"},'''

new = '''    \"511090\": {\"name\": \"30年国债ETF\", \"layer\": \"defense\", \"beta\": -0.1, \"liquidity\": 10.0,
               \"reason\": \"长久期利率债，对冲权益波动\"},
    \"511880\": {\"name\": \"银华日利ETF\", \"layer\": \"defense\", \"beta\": 0.0, \"liquidity\": 50.0,
               \"reason\": \"货币基金，现金管理工具\"},
    \"511990\": {\"name\": \"华宝添益ETF\", \"layer\": \"defense\", \"beta\": 0.0, \"liquidity\": 50.0,
               \"reason\": \"货币基金，现金管理工具\"},'''

assert old in c, "Could not find the target block in file!"
c = c.replace(old, new, 1)
open('E:/ETF_Surge/backend/app/services/strategy_design.py', 'w', encoding='utf-8').write(c)
print('Fixed: 511880 added to CANDIDATE_POOL as defense layer')
print(f'511880 count: {c.count("511880")}, 511990 count: {c.count("511990")}')
