"""Rebuild the editable INF2003 progress report with the primary Python runtime.
Run from the project root. Update verified status in docs/progress_status.json.
The output is a cover page plus exactly two body pages, using Calibri 12.
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / 'deliverables'
DIAG = ROOT / 'docs' / 'diagrams'
OUT.mkdir(exist_ok=True); DIAG.mkdir(parents=True, exist_ok=True)

def architecture():
    fig, ax = plt.subplots(figsize=(8.5, 2.2), dpi=220)
    ax.set(xlim=(0,10), ylim=(0,3)); ax.axis('off')
    nodes=[(.2,1,2.2,1,'Browser interface\nOrders  Stock  Feedback'),(3.05,1,2.8,1,'Python FastAPI backend\nAuthentication and business rules'),(6.7,1.65,3,1,'MariaDB with InnoDB\nOrders  Stock  Points'),(6.7,.2,3,1,'MongoDB\nReviews  Preferences')]
    for x,y,w,h,t in nodes:
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.03,rounding_size=.06',facecolor='#F1F4F7',edgecolor='#3E5267',linewidth=1.1))
        ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=9.3,color='#101820',linespacing=1.5)
    def arrow(a,b): ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'<->','color':'#3E5267','lw':1.2})
    arrow((2.4,1.5),(3.05,1.5)); arrow((5.85,1.75),(6.7,2.15)); arrow((5.85,1.25),(6.7,.7))
    fig.tight_layout(pad=.2)
    fig.savefig(DIAG/'architecture.png',bbox_inches='tight',facecolor='white')
    fig.savefig(DIAG/'architecture.svg',bbox_inches='tight',facecolor='white');plt.close(fig)

architecture()
status_file=ROOT/'docs'/'progress_status.json'
status=json.loads(status_file.read_text()) if status_file.exists() else {}
current=status.get('current_deliverables', 'The initial design includes the ER model, document schema, data ownership rules and a rubric evidence checklist. An initial implementation is being assembled with checkout, stock and loyalty services, review/profile APIs, data-loading scripts and four interface sections. Automated verification and real-database integration are pending; benchmark measurements have not yet been collected. The remaining work is integration, failure-case verification and reproducible evaluation before the final submission.')
d=Document()
s=d.sections[0];s.page_width=Inches(8.5);s.page_height=Inches(11);s.top_margin=Inches(.7);s.bottom_margin=Inches(.65);s.left_margin=Inches(.75);s.right_margin=Inches(.75)
for name in ['Normal','Body Text','Caption','Heading 1','Heading 2','Title','Subtitle']:
    st=d.styles[name];st.font.name='Calibri';st.font.size=Pt(12);st.font.color.rgb=RGBColor(0,0,0)
    st.paragraph_format.space_after=Pt(6)
    st.paragraph_format.line_spacing=1.03
    st.element.rPr.rFonts.set(qn('w:eastAsia'),'Calibri')
for style in d.styles:
    for border in list(style.element.findall('.//' + qn('w:pBdr'))):
        border.getparent().remove(border)
d.styles['Heading 1'].font.bold=True;d.styles['Heading 1'].paragraph_format.space_before=Pt(8);d.styles['Heading 1'].paragraph_format.space_after=Pt(5)
d.styles['Title'].font.size=Pt(23);d.styles['Title'].paragraph_format.space_after=Pt(14)
d.core_properties.title='HawkerFlow INF2003 Project Progress Report';d.core_properties.author='[GROUP MEMBER NAMES]';d.core_properties.subject='Local F&B inventory loyalty and feedback platform'

def p(text,style=None):
    x=d.add_paragraph(text,style);x.paragraph_format.widow_control=True;return x

def heading(text): return d.add_paragraph(text,'Heading 1')

def table(headers, rows, widths):
    t=d.add_table(rows=1,cols=len(headers));t.autofit=False
    for c,w in zip(t.columns,widths):c.width=Inches(w)
    for c,txt in zip(t.rows[0].cells,headers):c.text=txt
    for row in rows:
        cells=t.add_row().cells
        for c,txt in zip(cells,row):c.text=txt
    for i,row in enumerate(t.rows):
        trPr=row._tr.get_or_add_trPr()
        no=OxmlElement('w:cantSplit');trPr.append(no)
        if i==0: trPr.append(OxmlElement('w:tblHeader'))
        for j,c in enumerate(row.cells):
            c.width=Inches(widths[j]);tcPr=c._tc.get_or_add_tcPr()
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E6ECF2' if i==0 else ('FFFFFF' if i%2 else 'F5F7F9'));tcPr.append(shade)
            margins=OxmlElement('w:tcMar')
            for side in ['top','left','bottom','right']:
                e=OxmlElement('w:'+side);e.set(qn('w:w'),'70');e.set(qn('w:type'),'dxa');margins.append(e)
            tcPr.append(margins)
            borders=OxmlElement('w:tcBorders')
            for side in ['top','left','bottom','right']:
                e=OxmlElement('w:'+side);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
            tcPr.append(borders)
            v=OxmlElement('w:vAlign');v.set(qn('w:val'),'center');tcPr.append(v)
            for pp in c.paragraphs:
                pp.paragraph_format.space_after=Pt(0);pp.paragraph_format.line_spacing=1.0
                for r in pp.runs:r.font.name='Calibri';r.font.size=Pt(12);r.bold=i==0
    p('').paragraph_format.space_after=Pt(0)
    return t

# Cover page: placeholders deliberately retained for information not supplied.
p('Project Proposal Database Systems','Title').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('').paragraph_format.space_after=Pt(48)
p('HawkerFlow','Title').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('Local F&B Inventory Loyalty and Feedback Platform','Subtitle').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('').paragraph_format.space_after=Pt(52)
p('Team number: [GROUP NUMBER]').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('Student names: [MEMBER 1], [MEMBER 2], [MEMBER 3],\n[MEMBER 4], [MEMBER 5]').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('Date: [SUBMISSION DATE]').alignment=WD_ALIGN_PARAGRAPH.CENTER
p('').paragraph_format.space_after=Pt(70)
p('Submitted for INF2003 Database Systems').alignment=WD_ALIGN_PARAGRAPH.CENTER
d.add_page_break()
# Body page 1.
heading('Application Description')
p('HawkerFlow supports a small Singapore F&B chain that needs accurate ingredient stock, reliable loyalty rewards and useful customer feedback. Staff can complete sales and replenish stock; customers can view rewards and review their purchases; managers can inspect sales, shortages and recurring complaints. The objective is to connect these activities in one application while demonstrating both relational and document databases. Checkout must prevent overselling and update sales, stock and points together. The project covers completed cash sales; payment gateways, refunds and expiry-batch allocation are outside the initial scope.')
heading('System Architecture')
p('A browser interface communicates with a Python FastAPI backend. MariaDB with InnoDB owns customers, menu items, recipes, branch stock, orders and the points ledger. MongoDB owns review documents and optional customer preferences. SQL transactions protect checkout, while the backend verifies order ownership before accepting reviews. Shared identifiers link the stores; no cross-database foreign key is assumed. MongoDB outages do not undo completed SQL sales. Role checks separate manager, cashier and customer actions.')
d.add_picture(str(DIAG/'architecture.png'),width=Inches(6.95))
heading('Data')
p('The downloaded NEA snapshot contains 107 historical hawker-centre locations [1]; five supply addresses for fictional demonstration branches. The downloaded UCI Yelp subset contains 1,000 restaurant-review sentences with binary sentiment labels [2]. These remain in a separate external-example collection without invented order or branch links. Synthetic operational data use seed 20261002: 50 customers, 20 menu items, 15 ingredients and 200 orders, with generated purchase-linked reviews and profiles. Recipes, prices and quantities are teaching assumptions; source data and generated data remain clearly labelled.')
p('The SQL model includes Branches, Customers, Users, MenuItems, Ingredients, RecipeComponents, BranchStock, Orders, OrderLines, StockMovements, StockReceipts and LoyaltyTransactions. OrderLines resolve orders-to-items; RecipeComponents and BranchStock resolve further many-to-many relationships. Keys, foreign keys and quantity constraints protect integrity. Money uses DECIMAL, IDs and points use integers, dates use timestamps and postcodes use strings. MongoDB reviews embed tags, optional category ratings and bounded replies; profiles hold optional preferences. Validators and unique review-per-order indexes restrict invalid or duplicate documents.')
d.add_page_break()
# Body page 2.
heading('Functionalities and Implementation Plan')
p('Core SQL functions cover customer/menu management, audited restocking, order history and points history. Atomic checkout snapshots prices, locks affected stock, rejects shortages, records ingredient deductions and earns or redeems points. A unique request key prevents retry duplication. SQL analytics aggregate branch revenue and item sales, with reporting views and join-based analysis. Core MongoDB functions cover review CRUD, manager replies and profile updates. Aggregation pipelines count negative tags in low-rated reviews and summarize rating trends by branch and month.')
p('A separate benchmark compares equivalent review-tag analysis using SQL review/tag tables and MongoDB tag arrays. Identical generated inputs, validated results, documented indexes and repeated timings support a workload-specific comparison. Tests cover rollback, competing stock requests, retries, historical prices, redemption, access control and MongoDB validation. Real DBMS integration results are distinguished from tests using substitutes. Performance findings will be interpreted for the measured workload and environment.')
table(['Period','Milestone'],[
('2–4 Oct','Finalize design, verify data sources and submit progress report.'),
('5–18 Oct','Complete CRUD and data loading in both DBMSs; integrate interface.'),
('19 Oct–1 Nov','Verify checkout, loyalty, analytics, validation and indexes.'),
('2–15 Nov','Run integration, concurrency and matched benchmark experiments.'),
('16–29 Nov','Freeze features; finalize report, manual, slides and video; submit.')],[1.45,5.55])
p('Five workstreams cover SQL design, transactional services, MongoDB/analytics, backend/interface, and data/evaluation. Members will agree named ownership and review each other’s work. The final package will include a report of at most ten body pages, presentation slides, a video of at most ten minutes with all five members presenting, and a reproducible source/data/manual archive. The video will follow background, SQL implementation, NoSQL implementation and optional evaluation in that order.')
heading('Current Deliverables')
p(current)
# References excluded by the brief. Kept on body page 2 for compact delivery.
heading('References')
p('[1] National Environment Agency, “List of Government Markets Hawker Centres,” data.gov.sg, historical location records. Dataset: d_68a42f09f350881996d83f9cd73ab02f.\n[2] D. Kotzias, “Sentiment Labelled Sentences,” UCI Machine Learning Repository, 2015, doi: 10.24432/C57604. Yelp subset; CC BY 4.0.')
path=OUT/'HawkerFlow_INF2003_Progress_Report.docx';d.save(path);print(path)
