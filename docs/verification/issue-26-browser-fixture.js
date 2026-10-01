async page => {
  await page.unrouteAll();
  const keys = ['pairing','instagram','schedule','consent','logo','caption_template','cards'];
  const done = new Set(['pairing']);
  const state = {revoked:false,rejectToken:true,version:1,accepted:null,setupFailure:false,oauth:false};
  globalThis.issue26 = state;
  let branding = {logo_asset:null,intro_asset:null,intro_duration:null,outro_asset:null,outro_duration:null,caption_template:null};
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.route(/\/api\//,async route=>{
    const path=new URL(route.request().url()).pathname, method=route.request().method();
    if(!path.startsWith('/api/'))return route.continue();
    const reply=(value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
    if(path==='/api/compat')return reply({api_version:'0.1.0'});
    if(state.revoked)return reply({},401);
    if(path==='/api/pairing/me')return reply({id:1,name:'Dojo bilgisayarı',kind:'browser',created_at:'2026-10-01T10:00:00Z',created_by:'cli',last_seen_at:null,revoked_at:null});
    if(path==='/api/setup')return reply({ready:keys.slice(0,6).every(k=>done.has(k)),checklist:keys.map(key=>({key,label:key,complete:done.has(key),required:key!=='cards'}))},state.setupFailure?500:200);
    if(path==='/api/meta/status')return reply({health:done.has('instagram')?'healthy':'not_connected',ig_username:done.has('instagram')?'dojo_fixture':null});
    if(path==='/api/meta/instagram/token'){if(state.rejectToken)return reply({},422);done.add('instagram');return reply({health:'healthy',ig_username:'dojo_fixture'});}
    if(path==='/api/meta/oauth/start')return reply({auth_url:'https://www.facebook.com/dialog/oauth',attempt_id:'fixture'});
    if(path==='/api/meta/oauth/attempts/fixture')return reply({id:'fixture',status:'completed',candidates:[{ig_user_id:'1',ig_username:'one'},{ig_user_id:'2',ig_username:'two'}]});
    if(path==='/api/meta/oauth/attempts/fixture/select')return reply({health:'healthy',ig_username:'two'});
    if(path==='/api/settings/plan'){if(method==='PUT')done.add('schedule');return reply({anchor_date:'2026-10-05',anchor_time:'10:00:00',enabled:false,timezone:'Europe/Istanbul'});}
    if(path==='/api/setup/consent')return reply({version:state.version,text:'Fixture rıza metni '+state.version,accepted_at:state.accepted});
    if(path==='/api/setup/consent/accept'){if(route.request().postDataJSON().version!==state.version)return reply({},409);state.accepted='2026-10-01T10:00:00Z';done.add('consent');return reply({version:state.version,accepted_at:state.accepted});}
    if(path==='/api/settings/branding/assets')return reply({asset:'branding/assets/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png',preview_url:'/api/settings/branding/assets/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png'},201);
    if(path.startsWith('/api/settings/branding/assets/'))return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII=','base64')});
    if(path==='/api/settings/branding'){if(method==='PATCH'){branding={...branding,...route.request().postDataJSON()};if(branding.logo_asset)done.add('logo');if(branding.caption_template)done.add('caption_template');}return reply(branding);}
    if(path==='/api/setup/cards/skip'){done.add('cards');return reply({});}
    if(path==='/api/dashboard')return reply({generated_at:'2026-10-01T10:00:00Z',package:null,next_slot:null,pending_actions:[],plan:{anchor_date:'2026-10-05',anchor_time:'10:00:00',enabled:false,timezone:'Europe/Istanbul'},instagram:{health:'healthy',username:'dojo_fixture'},worker:{status:'healthy',phase:'idle'}});
    return reply({});
  });
  await page.goto('http://127.0.0.1:5176/?fixture26='+Date.now()+'#/dashboard');
  await page.getByRole('heading',{name:'Instagram bağlantısı'}).waitFor();
  const results=[];
  for(const width of [320,390,1280]){
    await page.setViewportSize({width,height:900});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow)throw new Error('horizontal overflow '+width);
    await page.screenshot({path:'docs/verification/issue-26-'+width+'.png',fullPage:true});results.push({width,overflow});
  }
  async function tabTo(locator){for(let i=0;i<100;i++){if(await locator.evaluate(el=>el===document.activeElement))return;await page.keyboard.press('Tab');}throw new Error('keyboard target unreachable');}
  await tabTo(page.getByLabel('Instagram erişim tokenı'));await page.keyboard.insertText('fixture-not-production');
  await tabTo(page.getByRole('button',{name:'Token ile bağlan'}));await page.keyboard.press('Enter');
  await page.getByRole('alert').filter({hasText:'Token geçersiz'}).waitFor();
  if(await page.getByLabel('Instagram erişim tokenı').inputValue()!=='')throw new Error('token retained');
  state.rejectToken=false;
  await tabTo(page.getByLabel('Instagram erişim tokenı'));await page.keyboard.insertText('fixture-not-production');
  await tabTo(page.getByRole('button',{name:'Token ile bağlan'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Dojo Yayın Planı'}).waitFor();
  await tabTo(page.getByRole('button',{name:'Planı kaydet'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Medya rızası'}).waitFor();
  await tabTo(page.getByRole('checkbox'));await page.keyboard.press('Space');state.version=2;
  await tabTo(page.getByRole('button',{name:'Rızayı kaydet'}));await page.keyboard.press('Enter');
  await page.getByText('Fixture rıza metni 2',{exact:true}).waitFor();
  if(await page.getByRole('checkbox').isChecked())throw new Error('stale acknowledgement');
  await tabTo(page.getByRole('checkbox'));await page.keyboard.press('Space');
  await tabTo(page.getByRole('button',{name:'Rızayı kaydet'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Dojo logosu'}).waitFor();
  await page.getByLabel('Logo görseli').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:Buffer.from('fixture')});
  await tabTo(page.getByRole('button',{name:'Logoyu kaydet'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Açıklama şablonu'}).waitFor();
  await tabTo(page.getByLabel('Açıklama şablonu'));await page.keyboard.insertText('Dojo fixture açıklaması');
  await tabTo(page.getByRole('button',{name:'Açıklamayı kaydet'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'İsteğe bağlı kartlar'}).waitFor();
  await tabTo(page.getByRole('button',{name:'Kartları değiştirmeden devam et'}));await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Kurulum tamamlandı'}).waitFor();
  await page.reload();await page.getByRole('heading',{name:'Kurulum tamamlandı'}).waitFor();
  const storage=await page.evaluate(()=>localStorage.length+sessionStorage.length);
  await page.getByRole('link',{name:'Kurulumu bitir'}).click();await page.getByRole('heading',{name:'Kontrol Paneli'}).waitFor();
  await page.getByRole('link',{name:'Ayarlar',exact:true}).click();await page.getByRole('link',{name:'Kurulumu aç'}).click();await page.getByRole('heading',{name:'Kurulum tamamlandı'}).waitFor();
  await page.getByRole('button',{name:/Instagram bağlantısı Tamamlandı/}).click();
  await page.getByRole('button',{name:'Instagram ile yetkilendir'}).click();
  await page.getByRole('button',{name:'@two hesabını seç'}).waitFor();
  await page.getByRole('button',{name:'@two hesabını seç'}).click();
  await page.getByRole('heading',{name:'Kurulum tamamlandı'}).waitFor();
  state.setupFailure=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.getByRole('alert').waitFor();
  state.setupFailure=false;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.getByRole('alert').waitFor({state:'hidden'});
  await page.getByRole('button',{name:/Açıklama şablonu Tamamlandı/}).click();
  await page.getByLabel('Açıklama şablonu').fill('Protected draft');
  branding.caption_template='Other device';
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.getByRole('button',{name:'Sunucudaki değerleri yükle'}).waitFor();
  if(await page.getByLabel('Açıklama şablonu').inputValue()!=='Protected draft')throw new Error('dirty draft lost');
  await page.getByRole('button',{name:'Sunucudaki değerleri yükle'}).click();
  if(await page.getByLabel('Açıklama şablonu').inputValue()!=='Other device')throw new Error('explicit reload failed');
  state.revoked=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.getByRole('heading',{name:'Tarayıcıyı eşleştir'}).waitFor();
  return {results,storage,errors,flow:'token rejection/success, disabled plan, stale policy 409, logo/caption, cards skip, reload/reopen, OAuth picker, stale read recovery, dirty draft/explicit reload, finish and session revocation passed; keyboard navigation except injected file chooser'};
}
