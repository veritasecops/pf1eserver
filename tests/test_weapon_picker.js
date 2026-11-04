const test = require('node:test');
const assert = require('node:assert/strict');
const {copper,summarize} = require('../static/weapon-picker.js');
const equipment = {
  longsword:{name:'Longsword',kind:'weapon',cost:1500},
  dagger:{name:'Dagger',kind:'weapon',cost:200},
  shield:{name:'Shield',kind:'weapon',cost:null},
  arrows:{name:'Arrows',kind:'gear',category:'ammunition',cost:100},
  leather:{name:'Leather',kind:'armor',cost:1000}
};
const total = values => summarize({equipment,quantities:{},prices:{},owned:{},budget:10000,...values});

test('gold prices convert exactly to copper and reject partial copper values',()=>{
  assert.equal(copper('0.29'),29);
  assert.equal(copper('12.3'),1230);
  assert.equal(copper('0'),0);
  for(const value of ['', '-1','1.001','NaN','Infinity'])assert.equal(copper(value),null);
});
test('pending quantities across search results share a single running total without changing inventory',()=>{
  const owned={longsword:1},quantities={longsword:'2',dagger:'3',arrows:'1'};
  const result=total({owned,quantities});
  assert.equal(result.total,3700);
  assert.equal(result.remaining,6300);
  assert.equal(result.units,6);
  assert.deepEqual(result.quantities,{longsword:2,dagger:3,arrows:1});
  assert.deepEqual(owned,{longsword:1});
  assert.equal(quantities.longsword,'2');
});
test('special prices, over-budget selections and inventory limits prevent submission',()=>{
  assert.equal(total({quantities:{shield:'2'}}).errors.length,1);
  const priced=total({quantities:{shield:'2'},prices:{shield:'9.50'}});
  assert.equal(priced.total,1900);
  assert.deepEqual(priced.prices,{shield:950});
  assert.equal(total({quantities:{longsword:'10'}}).errors.length,1);
  assert.equal(total({quantities:{dagger:'2'},owned:{dagger:99}}).errors.length,1);
  assert.equal(total({quantities:{dagger:'1.5'}}).errors.length,1);
  assert.deepEqual(total({quantities:{leather:'1'}}).errors,[]);
});
test('free selections are allowed at zero balance and unselected special prices do not block the cart',()=>{
  const result=total({equipment:{...equipment,staff:{name:'Staff',kind:'weapon',cost:0}},quantities:{staff:1,shield:0},budget:0});
  assert.equal(result.units,1);
  assert.equal(result.remaining,0);
  assert.deepEqual(result.errors,[]);
});
test('character sheet row limits allow more copies but cap new weapon types',()=>{
  assert.equal(total({quantities:{longsword:1,dagger:1},maxNewWeapons:1}).errors.length,1);
  assert.deepEqual(total({quantities:{longsword:1,dagger:1},owned:{longsword:2},maxNewWeapons:1}).errors,[]);
});

test('mixed armor and weapon carts share treasure and enforce separate row limits',()=>{
  const catalog={...equipment,mail:{kind:'armor',name:'Mail',cost:5000},buckler:{kind:'shield',name:'Buckler',cost:500},extra:{kind:'gear',category:'extra',name:'Spikes',cost:1000}};
  const result=total({equipment:catalog,quantities:{mail:1,dagger:1,buckler:2,extra:1},maxNewArmor:2,maxNewWeapons:0});
  assert.equal(result.total,7200);
  assert.equal(result.errors.length,1);
  assert.deepEqual(total({equipment:catalog,quantities:{mail:1,buckler:1},maxNewArmor:1,owned:{mail:1}}).errors,[]);
  assert.equal(total({equipment:catalog,quantities:{mail:1,buckler:1},maxNewArmor:1}).errors.length,1);
});
