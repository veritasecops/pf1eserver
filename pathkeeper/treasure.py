"""On-hand coins from Archives of Nethys, Core Rulebook Table 6-2.
Source: https://www.aonprd.com/Rules.aspx?ID=107
"""
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException

COINS = {'pp':1000,'gp':100,'sp':10,'cp':1}
COIN_TYPES = [('cp','Copper pieces','0.01'),('sp','Silver pieces','0.1'),
              ('gp','Gold pieces','1'),('pp','Platinum pieces','10')]

def treasure(values):
    total=Decimal(0)
    for coin,factor in COINS.items():
        try: amount=Decimal(str(values.get('money.'+coin,'') or '0'))
        except InvalidOperation: raise HTTPException(422,'Enter valid on-hand coin amounts.') from None
        if not amount.is_finite() or amount<0 or amount>1000000000: raise HTTPException(422,'Enter nonnegative on-hand coin amounts.')
        total+=amount*factor
    if total!=total.to_integral_value(): raise HTTPException(422,'Treasure must total a whole number of copper pieces.')
    return int(total)


def deduct_coins(values, cost):
    remaining=treasure(values)-cost
    if remaining<0: raise HTTPException(422,'These weapons exceed the character’s on-hand treasure.')
    counts={}
    for coin,factor in COINS.items():
        original=int(Decimal(str(values.get('money.'+coin,'') or '0')))
        counts[coin]=min(original,remaining//factor)
        remaining-=counts[coin]*factor
    # Make change only when the existing denominations cannot cover the purchase.
    for coin,factor in COINS.items():
        change,remaining=divmod(remaining,factor)
        counts[coin]+=change
    return {'money.'+coin:str(count) for coin,count in counts.items()}

