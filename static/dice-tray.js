/* Code-native polyhedra, perspective projection, and animation. Results come from the server. */
(() => {
  const add=(a,b)=>a.map((v,i)=>v+b[i]), sub=(a,b)=>a.map((v,i)=>v-b[i]), mul=(a,s)=>a.map(v=>v*s), dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]], unit=a=>mul(a,1/Math.hypot(...a));
  function hull(vertices){
    const faces=[], seen=new Set(), eps=1e-5;
    for(let a=0;a<vertices.length;a++)for(let b=a+1;b<vertices.length;b++)for(let c=b+1;c<vertices.length;c++){
      let normal=cross(sub(vertices[b],vertices[a]),sub(vertices[c],vertices[a])); if(Math.hypot(...normal)<eps)continue;
      normal=unit(normal);let distance=dot(normal,vertices[a]);let sides=vertices.map(v=>dot(normal,v)-distance);
      if(sides.every(v=>v>=-eps)){normal=mul(normal,-1);distance=-distance;sides=sides.map(v=>-v);}else if(!sides.every(v=>v<=eps))continue;
      const ids=vertices.map((_,i)=>i).filter(i=>Math.abs(sides[i])<eps),key=ids.join(',');if(seen.has(key))continue;seen.add(key);
      const center=mul(ids.reduce((s,i)=>add(s,vertices[i]),[0,0,0]),1/ids.length),u=unit(sub(vertices[ids[0]],center)),v=cross(normal,u);
      ids.sort((i,j)=>Math.atan2(dot(sub(vertices[i],center),v),dot(sub(vertices[i],center),u))-Math.atan2(dot(sub(vertices[j],center),v),dot(sub(vertices[j],center),u)));
      faces.push({ids,normal,distance});
    }return faces;
  }
  function mesh(vertices){const scale=Math.max(...vertices.map(v=>Math.hypot(...v)));vertices=vertices.map(v=>mul(v,1/scale));return{vertices,faces:hull(vertices)};}
  function dual(source){return mesh(source.faces.map(face=>mul(face.normal,1/face.distance)));}
  const phi=(1+Math.sqrt(5))/2,ico=[];
  for(const a of [-1,1])for(const b of [-phi,phi])ico.push([0,a,b],[a,b,0],[b,0,a]);
  const cube=[];for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1])cube.push([x,y,z]);
  const anti=[];for(let i=0;i<5;i++){const a=i*Math.PI*2/5;anti.push([Math.cos(a),Math.sin(a),.55],[Math.cos(a+Math.PI/5),Math.sin(a+Math.PI/5),-.55]);}
  const meshes={4:mesh([[1,1,1],[1,-1,-1],[-1,1,-1],[-1,-1,1]]),6:mesh(cube),8:mesh([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]]),20:mesh(ico)};
  meshes[12]=dual(meshes[20]);meshes[10]=dual(mesh(anti));
  const rotate=(v,x,y,z)=>{let [a,b,c]=v;[b,c]=[b*Math.cos(x)-c*Math.sin(x),b*Math.sin(x)+c*Math.cos(x)];[a,c]=[a*Math.cos(y)+c*Math.sin(y),-a*Math.sin(y)+c*Math.cos(y)];return[a*Math.cos(z)-b*Math.sin(z),a*Math.sin(z)+b*Math.cos(z),c];};
  window.PathkeeperDice=class {
    constructor(canvas){this.canvas=canvas;this.captionFont=getComputedStyle(canvas).font;this.ctx=canvas.getContext('2d');this.items=[{sides:20,value:20}];this.busy=false;this.startAt=performance.now();this.finishAt=null;this.frame=null;this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;this.observer=new ResizeObserver(()=>this.draw(performance.now()));this.observer.observe(canvas);this.draw(performance.now());}
    spin(sides,count){this.items=Array.from({length:sides===100?count*2:count},(_,i)=>({sides:sides===100?10:sides,value:null,tens:sides===100&&i%2===0,units:sides===100&&i%2===1}));this.busy=true;this.finishAt=null;this.startAt=performance.now();this.animate();}
    settle(record){const result=record.result;this.items=[];
      if(record.purpose==='ability'){result.groups.forEach(group=>group.dice.forEach((value,index)=>this.items.push({sides:6,value,dropped:index===group.dropped})));}
      else if(result.sides===100){result.percentile.forEach(pair=>{this.items.push({sides:10,value:String(pair.tens).padStart(2,'0'),tens:true},{sides:10,value:pair.ones,units:true});});}
      else this.items=result.dice.map(value=>({sides:result.sides,value}));
      this.finishAt=performance.now();this.busy=false;if(this.reduced){this.finishAt-=1400;this.draw(performance.now());}else this.animate();
    }
    stop(){this.busy=false;this.finishAt=performance.now()-1400;this.draw(performance.now());}
    animate(){if(this.frame)return;const tick=now=>{this.frame=null;this.draw(now);if(this.busy||this.finishAt&&now-this.finishAt<1350)this.frame=requestAnimationFrame(tick);};this.frame=requestAnimationFrame(tick);}
    draw(now){const rect=this.canvas.getBoundingClientRect();if(!rect.width)return;const ratio=Math.min(2,devicePixelRatio||1),width=rect.width,height=rect.height;
      if(this.canvas.width!==Math.round(width*ratio)||this.canvas.height!==Math.round(height*ratio)){this.canvas.width=Math.round(width*ratio);this.canvas.height=Math.round(height*ratio);}const ctx=this.ctx;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
      const glow=ctx.createRadialGradient(width*.5,height*.4,0,width*.5,height*.45,width*.7);glow.addColorStop(0,'#b9813e38');glow.addColorStop(1,'#2d190e00');ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);
      ctx.strokeStyle='#ffffff08';ctx.lineWidth=1;for(let i=0;i<8;i++){ctx.beginPath();ctx.moveTo(width*.5+(i-3.5)*18,height*.48);ctx.lineTo((i-3.5)*65+width*.5,height);ctx.stroke();}for(let i=0;i<5;i++){ctx.beginPath();ctx.moveTo(0,height*.6+i*height*.085);ctx.lineTo(width,height*.6+i*height*.085);ctx.stroke();}
      const count=this.items.length,cols=count===1?1:count<=4?2:count<=9?3:count<=20?4:6,rows=Math.ceil(count/cols),cellW=width/(cols+.35),cellH=(height-35)/(rows+.2),radius=Math.min(cellW*.38,cellH*.40,74);
      const elapsed=(now-this.startAt)/1000,progress=this.finishAt===null?0:Math.min(1,(now-this.finishAt)/1200),motion=this.reduced?0:this.busy?1:Math.pow(1-progress,3);
      this.items.forEach((item,index)=>{const source=meshes[item.sides]||meshes[20],row=Math.floor(index/cols),col=index%cols,last=Math.min(cols,count-row*cols),cx=width*.5+(col-(last-1)*.5)*cellW,cy=(row+.5)*cellH+18-Math.abs(Math.sin(elapsed*8+index))*(motion*23),angle=motion*(elapsed*6+index*1.7);
        ctx.beginPath();ctx.ellipse(cx,cy+radius*.84,radius*.8,radius*.15,0,0,Math.PI*2);ctx.fillStyle='#00000030';ctx.fill();
        const points=source.vertices.map(v=>rotate(v,.48+angle,.65+angle*.75,.12+angle*.4)),faces=source.faces.map((face,i)=>({...face,index:i,n:rotate(face.normal,.48+angle,.65+angle*.75,.12+angle*.4)})).filter(face=>face.n[2]>0).sort((a,b)=>a.n[2]-b.n[2]),front=faces.at(-1)?.index;
        faces.forEach(face=>{const projected=face.ids.map(i=>{const v=points[i],scale=4/(4-v[2]);return[cx+v[0]*radius*scale,cy-v[1]*radius*scale];});ctx.beginPath();projected.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();const light=Math.round(28+face.n[2]*26);ctx.fillStyle=item.dropped?`hsl(35,8%,${light-5}%)`:item.tens?`hsl(40,36%,${light}%)`:`hsl(18,42%,${light}%)`;ctx.fill();ctx.lineWidth=1;ctx.strokeStyle=item.dropped?'#baa47c45':'#ebcd8aa0';ctx.stroke();
          if(face.index!==front&&face.n[2]<0.45)return;
          const center=projected.reduce((s,p)=>[s[0]+p[0]/projected.length,s[1]+p[1]/projected.length],[0,0]);let pip=face.index%item.sides;if(item.value===null)pip=Math.floor(elapsed*11+index+face.index)%item.sides;let label=item.tens?String(pip*10).padStart(2,'0'):item.units?pip:pip+1;if(face.index===front&&item.value!==null)label=item.value;
          ctx.save();ctx.translate(...center);ctx.fillStyle=item.dropped?'#d6bc9178':'#fff7e7';ctx.font=`600 ${Math.max(9,radius*(face.index===front ? 0.5 : 0.27))}px Georgia`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(label),0,0);ctx.restore();
        });
      });
      ctx.fillStyle='#dbc08d';ctx.font=this.captionFont;ctx.textAlign='center';ctx.fillText(this.busy?'ROLLING…':'PATHKEEPER · YOUR TABLE, YOUR DICE',width/2,height-8);
    }
  };
})();
