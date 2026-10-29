const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const context={};vm.createContext(context);
for(const [file,names] of [['lib/accounting.js','premiumMoney'],['endorsementRules.js','insuranceIssues,markRenewalPremium,recomputeRenewal']]){
 const code=fs.readFileSync(path.join(__dirname,'../src/alpha',file),'utf8').replace(/^import .*$/gm,'').replace(/export /g,'');
 vm.runInContext('(function(){'+code+'\nObject.assign(globalThis,{'+names+'});})()',context);
}
let count=0;function check(name,ok){assert(ok,name);count++;console.log('PASS '+name)}
const p={reinsuranceStructure:'QS',parentTwRef:'ROOT',policyFrom:'2026-03-01',policyTo:'2027-03-01',endoTypes:['Premium'],endoEffectiveDate:'2027-03-01',endorsementSource:{policyFrom:'2026-03-01',policyTo:'2027-03-01',previousEffectiveDate:'2026-09-01'}};
check('general endorsement accepts expiry date',context.insuranceIssues(p).length===0);
check('general endorsement accepts start date with no predecessor',context.insuranceIssues({...p,endoEffectiveDate:p.policyFrom,endorsementSource:{...p.endorsementSource,previousEffectiveDate:''}}).length===0);
check('general endorsement refuses after expiry',context.insuranceIssues({...p,endoEffectiveDate:'2027-03-02'}).some(x=>x.field==='endoEffectiveDate'));
check('Period permits outside old coverage while respecting complete duration',context.insuranceIssues({...p,policyTo:'2027-09-01',endoEffectiveDate:'2027-08-01',endoTypes:['Period']}).length===0);
check('removing Period after editing dates is blocked',context.insuranceIssues({...p,policyTo:'2027-09-01'}).some(x=>x.field==='endoTypes'));
check('chronological ordering remains required',context.insuranceIssues({...p,endoEffectiveDate:'2026-08-31'}).some(x=>x.label.includes('preceding')));
check('incomplete effective date is a formal error',context.insuranceIssues({...p,endoEffectiveDate:'2027-03'}).some(x=>x.field==='endoEffectiveDate'));
const span={reinsuranceStructure:'XOL',policyFrom:'2026-08-31',policyTo:'2028-02-29'};
check('18 calendar months supports leap-month clamping',context.insuranceIssues(span).length===0);
check('day after 18-month boundary is blocked',context.insuranceIssues({...span,policyTo:'2028-03-01'}).some(x=>x.field==='policyTo'));
const r={currency:'USD',policyFrom:'2047-09-01',policyTo:'2048-09-01',originalPremium:73200,reinsurers:[{name:'QA Re A',premium:58560},{name:'QA Re B',premium:51240}],renewalPremiumBasis:{sourceDays:549,totals:{originalPremium:109800,'reinsurers.0.premium':87840,'reinsurers.1.premium':76860},names:['qa re a','qa re b'],auto:{},manual:[]}};
context.recomputeRenewal(r);check('daily average uses actual leap-year renewal days',r.originalPremium===73200 && r.reinsurers[1].premium===51240);
context.markRenewalPremium(r,'originalPremium');r.originalPremium=50000;context.markRenewalPremium(r,'reinsurers.0.premium');r.reinsurers[0].premium=33333;
r.policyTo='2048-03-01';context.recomputeRenewal(r);
check('manual premiums survive automatic period recomputation',r.originalPremium===50000 && r.reinsurers[0].premium===33333);
check('remaining premiums use actual new duration',r.reinsurers[1].premium===25480);
r.policyTo='unfinished';context.recomputeRenewal(r);
check('invalid target dates do not fabricate automatic money',r.reinsurers[1].premium===null && r.originalPremium===50000);
console.log(`${count}/${count} endorsement frontend rules checks passed`);
