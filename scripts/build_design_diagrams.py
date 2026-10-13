from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
OUT=Path(__file__).resolve().parents[1]/'docs'/'diagrams'
OUT.mkdir(parents=True,exist_ok=True)
fig,ax=plt.subplots(figsize=(16,10.5),dpi=180)
ax.set_xlim(-.8,16.8);ax.set_ylim(-.4,10.4);ax.axis('off')
w=3.25;h=2.0
nodes={
'customers':(0,7.5,'id PK INTEGER\nname VARCHAR\nemail UNIQUE VARCHAR'),
'users':(4.25,7.5,'id PK INTEGER\ncustomer_id FK nullable\nbranch_id FK nullable\nemail UNIQUE; password_hash\nrole; is_active'),
'branches':(8.5,7.5,'id PK INTEGER\nname; address VARCHAR\npostal_code VARCHAR(6)'),
'stock_receipts':(12.75,7.5,'id PK INTEGER\nrequest_key UNIQUE\nbranch_id; ingredient_id FK\nquantity DECIMAL > 0\ncreated_at DATETIME'),
'orders':(0,4.2,'id PK INTEGER\nbranch_id; customer_id FK\nrequest_key UNIQUE; hash\ntotal DECIMAL; redeemed INT\nstatus; created_at'),
'order_lines':(4.25,4.2,'id PK INTEGER\norder_id; menu_item_id FK\nquantity INTEGER > 0\nunit_price DECIMAL\nnotes VARCHAR'),
'branch_stock':(8.5,4.2,'branch_id PK FK\ningredient_id PK FK\nquantity DECIMAL >= 0\nreorder_level DECIMAL >= 0'),
'stock_movements':(12.75,4.2,'id PK INTEGER\nbranch_id; ingredient_id FK\norder_id FK nullable\nquantity_delta DECIMAL\nreason; created_at'),
'loyalty_transactions':(0,.9,'id PK INTEGER\ncustomer_id FK\norder_id FK nullable\npoints_delta INTEGER\nevent_type; created_at'),
'menu_items':(4.25,.9,'id PK INTEGER\nname; category VARCHAR\nprice DECIMAL >= 0\nis_active BOOLEAN'),
'recipe_components':(8.5,.9,'menu_item_id PK FK\ningredient_id PK FK\nquantity DECIMAL > 0'),
'ingredients':(12.75,.9,'id PK INTEGER\nname UNIQUE VARCHAR\nunit VARCHAR')}
# Orthogonal corridors keep every relationship visible outside table boxes.
def side(name,side):
 x,y,_=nodes[name]
 return {'L':(x,y+h/2),'R':(x+w,y+h/2),'T':(x+w/2,y+h),'B':(x+w/2,y)}[side]
def edge(a,sa,b,sb,via=(),labelpos=None):
 pa,pb=side(a,sa),side(b,sb); points=[pa,*via,pb]
 for start,end in zip(points[:-2],points[1:-1]):
  ax.plot([start[0],end[0]],[start[1],end[1]],lw=1.1,color='#64798C',zorder=1)
 ax.add_patch(FancyArrowPatch(points[-2],points[-1],arrowstyle='-|>',mutation_scale=12,lw=1.1,color='#64798C',zorder=1))
 if labelpos is None and not via:labelpos=((pa[0]+pb[0])/2,(pa[1]+pb[1])/2)
 if labelpos:
  ax.text(*labelpos,'1 : N',fontsize=8.5,color='#294154',ha='center',va='center',bbox={'facecolor':'white','edgecolor':'none','pad':1},zorder=2)
edge('customers','B','orders','T')
edge('orders','R','order_lines','L')
edge('menu_items','T','order_lines','B')
edge('branches','B','branch_stock','T')
edge('branches','R','stock_receipts','L')
edge('branches','B','orders','T',[(10.125,7.05),(1.625,7.05)],(6,7.05))
edge('ingredients','L','recipe_components','R')
edge('menu_items','R','recipe_components','L')
edge('ingredients','T','stock_movements','B')
edge('ingredients','T','branch_stock','B',[(14.375,3.65),(10.125,3.65)],(11.8,3.65))
edge('branches','B','stock_movements','T',[(10.125,6.65),(14.375,6.65)],(12.2,6.65))
edge('orders','B','loyalty_transactions','T')
edge('customers','L','loyalty_transactions','L',[(-.55,8.5),(-.55,1.9)],(-.55,5.2))
edge('customers','R','users','L')
edge('branches','L','users','R')
edge('ingredients','R','stock_receipts','R',[(16.5,1.9),(16.5,8.5)],(16.5,5.2))
edge('orders','R','stock_movements','L',[(3.75,5.2),(3.75,6.4),(12.25,6.4),(12.25,5.2)],(8,6.4))
for name,(x,y,fields) in nodes.items():
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.015,rounding_size=.06',facecolor='white',edgecolor='#334E68',linewidth=1.25,zorder=3))
 ax.add_patch(FancyBboxPatch((x,y+h-.45),w,.45,boxstyle='round,pad=.015,rounding_size=.05',facecolor='#E8EFF5',edgecolor='#334E68',linewidth=.7,zorder=4))
 ax.text(x+w/2,y+h-.225,name,fontsize=11.1,weight='bold',ha='center',va='center',zorder=5)
 ax.text(x+.13,y+h-.57,fields,fontsize=10.2,linespacing=1.35,ha='left',va='top',zorder=5)
ax.text(8,10.15,'HawkerFlow operational SQL model',fontsize=18,weight='bold',ha='center')
ax.text(8,.18,'Arrows run from parent to child. Optional customer, branch and order foreign keys are marked nullable.\nFull constraints and widths: app/models.py. Benchmark review tables are independent and omitted here.',fontsize=10,ha='center',va='center')
fig.tight_layout(pad=.3)
fig.savefig(OUT/'erd.png',bbox_inches='tight',facecolor='white');fig.savefig(OUT/'erd.svg',bbox_inches='tight',facecolor='white')
plt.close(fig)
