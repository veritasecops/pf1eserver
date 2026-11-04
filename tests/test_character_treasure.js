const test=require('node:test');
const assert=require('node:assert/strict');
const {balance}=require('../static/character-treasure.js');

test('coin types use the published copper silver gold platinum exchange rates',()=>{
  assert.deepEqual(balance({cp:'1',sp:'1',gp:'1',pp:'1'}),{copper:1111,gp:11.11});
  assert.deepEqual(balance({gp:'141'}),{copper:14100,gp:141});
});
test('blank or removed holdings have zero value and existing fractional gold stays readable',()=>{
  assert.deepEqual(balance({cp:'',gp:'0'}),{copper:0,gp:0});
  assert.deepEqual(balance({gp:'10.50',cp:'2'}),{copper:1052,gp:10.52});
});
test('invalid negative nonfinite and sub-copper balances are rejected',()=>{
  for(const amounts of [{gp:'-1'},{cp:'0.5'},{gp:'0.001'},{pp:'Infinity'},{gp:'NaN'},{gp:'1000000001'}]) assert.ok(balance(amounts).error);
});
test('large valid coin totals remain exact within the supported bounds',()=>{
  assert.deepEqual(balance({pp:'1000000000',gp:'1',sp:'1',cp:'1'}),{copper:1000000000111,gp:10000000001.11});
});
