(function(global){
  'use strict';
  const DEFAULT_HEADERS=['Original Insured','Reinsured','Reinsurer / RI Broker','Class','Type','Currency','Exch. Rate','A/E','Eff Date','Exp Date','Comm (%)','Premium (NTD)','Income (NTD)','Policy No','Endorse No','Remark','Tranx Date'];
  function dateSlashes(value){return String(value||'').slice(0,10).replace(/-/g,'/');}
  function cellValue(row,index){return [row.originalInsured,row.reinsured,row.reinsurer,row.classCode,row.type,row.currency,row.rate,row.ae,dateSlashes(row.effDate),dateSlashes(row.expDate),Math.round((Number(row.comm||0)+Number.EPSILON)*100)/100,row.premium,row.income,row.policyNo,row.endorseNo,row.remark,dateSlashes(row.tranxDate)][index];}
  function excelColumn(index){let s='';for(let x=index+1;x;x=Math.floor((x-1)/26))s=String.fromCharCode(65+(x-1)%26)+s;return s;}
  function xml(value){return String(value==null?'':value).replace(/[<>&"']/g,ch=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[ch]));}
  function sheetXml(rows,headers){
    const all=[headers].concat(rows.map(row=>headers.map((_,i)=>cellValue(row,i))));
    const sheetRows=all.map((values,rIndex)=>'<row r="'+(rIndex+1)+'">'+values.map((value,cIndex)=>{
      const ref=excelColumn(cIndex)+(rIndex+1),numeric=rIndex>0&&[6,10,11,12].includes(cIndex)&&value!=='';
      const style=rIndex===0?1:(rIndex>0&&[11,12].includes(cIndex)&&Number(value)<0?2:(rIndex>0&&[6,10].includes(cIndex)?3:(rIndex>0&&[11,12].includes(cIndex)?4:0)));
      return numeric?'<c r="'+ref+'" s="'+style+'"><v>'+Number(value)+'</v></c>':'<c r="'+ref+'" s="'+style+'" t="inlineStr"><is><t>'+xml(value)+'</t></is></c>';
    }).join('')+'</row>').join('');
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>'+headers.map((h,i)=>'<col min="'+(i+1)+'" max="'+(i+1)+'" width="'+([0,1,2].includes(i)?28:[13,14].includes(i)?18:14)+'" customWidth="1"/>').join('')+'</cols><sheetData>'+sheetRows+'</sheetData><autoFilter ref="A1:Q'+Math.max(1,all.length)+'"/></worksheet>';
  }
  async function blob(report,headers){
    if(!global.JSZip)throw new Error('Excel generator is unavailable.');
    const zip=new global.JSZip(),stable={date:new Date(Date.UTC(1980,0,1))},cols=headers||DEFAULT_HEADERS;
    zip.file('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',stable);
    zip.file('_rels/.rels','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',stable);
    zip.file('xl/workbook.xml','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Production Report '+xml(report.month)+'" sheetId="1" r:id="rId1"/></sheets></workbook>',stable);
    zip.file('xl/_rels/workbook.xml.rels','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',stable);
    zip.file('xl/styles.xml','<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="3"><numFmt numFmtId="164" formatCode="0.00"/><numFmt numFmtId="165" formatCode="#,##0"/><numFmt numFmtId="166" formatCode="[Red]-#,##0"/></numFmts><fonts count="3"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font><font><color rgb="FFFF0000"/><sz val="11"/><name val="Arial"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="166" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs></styleSheet>',stable);
    zip.file('xl/worksheets/sheet1.xml',sheetXml(Array.isArray(report.rows)?report.rows:[],cols),stable);
    return zip.generateAsync({type:'blob',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  }
  function downloadBlob(file,filename){const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);}
  global.RIProductionXlsx={
    async download(report,headers){const file=await blob(report,headers);downloadBlob(file,`Production_Report_${report.month}_V${report.version}.xlsx`);},
    blob
  };
})(window);