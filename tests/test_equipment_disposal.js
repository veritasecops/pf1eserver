const test=require('node:test');
const assert=require('node:assert/strict');
const {proceeds}=require('../static/equipment-disposal.js');
test('sale proceeds retain the denomination and total exactly',()=>{
  assert.deepEqual(proceeds({pp:'2',gp:'3',sp:'4',cp:'5'}),{coins:{pp:2,gp:3,sp:4,cp:5},copper:2345});
});
test('reject fractional, negative, missing, and oversized coins',()=>{
  for(const value of ['-1','1.5','','1e3','NaN','1000000001'])assert.throws(()=>proceeds({pp:'0',gp:value,sp:'0',cp:'0'}));
});
