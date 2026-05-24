PS H:\Dokumenter\GitHub\dcs-retribution2\client> python -c "
>> content = open('H:/Dokumenter/GitHub/dcs-retribution2/client/src/components/dropzonelayer/DropZoneLayer.tsx', 'w', encoding='utf-8')
>> content.write('''import { LatLng } from \"leaflet\";
>> import React, { useState } from \"react\";
>> import {
>>   CircleMarker,
>>   Polyline,
>>   Popup,
>>   Tooltip,
>>   useMapEvents,
>> } from \"react-leaflet\";
>> import { useAppDispatch, useAppSelector } from \"../../app/hooks\";
>> import {
>>   DropZone,
>>   deleteDropZone,
>>   selectDropZones,
>>   serverBase,
>> } from \"../../api/dropZonesSlice\";
>> import {
>>   createConvoyRoute,
>>   deleteConvoyRoute,
>>   selectConvoyRoutes,
>> } from \"../../api/convoyRoutesSlice\";
>> import type { ConvoyRoute } from \"../../api/convoyRoutesSlice\";
>>
>> const popupWrap: React.CSSProperties = { minWidth: 210 };
>> const menuWrap: React.CSSProperties = { minWidth: 200, padding: \"4px 0\" };
>> const menuItem: React.CSSProperties = { display: \"block\", width: \"100%\", background: \"transparent\", color: \"#ecf0f1\", border: \"none\", borderRadius: 0, padding: \"8px 14px\", cursor: \"pointer\", fontSize: 13, textAlign: \"left\" };
>> const menuDivider: React.CSSProperties = { borderTop: \"1px solid #444\", margin: \"4px 0\" };
  File "<string>", line 3
    content.write('''import { LatLng } from " leaflet\;
                  ^
SyntaxError: unterminated triple-quoted string literal (detected at line 4)
PS H:\Dokumenter\GitHub\dcs-retribution2\client> const inputStyle: React.CSSProperties = { display: \"block\", width: \"100%\", marginTop: 8, background: \"#1a252f\", color: \"#ecf0f1\", border: \"1px solid #555\", borderRadius: 3, padding: \"5px 7px\", fontSize: 12, boxSizing: \"border-box\" };
const : The term 'const' is not recognized as the name of a cmdlet, function, script file, or operable program. Check
the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:1
+ const inputStyle: React.CSSProperties = { display: \"block\", width:  ...
+ ~~~~~
    + CategoryInfo          : ObjectNotFound: (const:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client> const btn: React.CSSProperties = { background: \"#2c3e50\", color: \"#ecf0f1\", border: \"1px solid #555\", borderRadius: 4, padding: \"5px 10px\", cursor: \"pointer\", fontSize: 12 };
const : The term 'const' is not recognized as the name of a cmdlet, function, script file, or operable program. Check
the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:1
+ const btn: React.CSSProperties = { background: \"#2c3e50\", color: \" ...
+ ~~~~~
    + CategoryInfo          : ObjectNotFound: (const:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client> const dangerBtn: React.CSSProperties = { ...btn, background: \"#7b241c\" };
At line:1 char:48
+ const dangerBtn: React.CSSProperties = { ...btn, background: \"#7b241 ...
+                                                ~
Missing argument in parameter list.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : MissingArgument

PS H:\Dokumenter\GitHub\dcs-retribution2\client> const ROUTE_COLOR = \"#f5a623\";
const : The term 'const' is not recognized as the name of a cmdlet, function, script file, or operable program. Check
the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:1
+ const ROUTE_COLOR = \"#f5a623\";
+ ~~~~~
    + CategoryInfo          : ObjectNotFound: (const:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client> const PENDING_COLOR = \"#ffffff\";
const : The term 'const' is not recognized as the name of a cmdlet, function, script file, or operable program. Check
the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:1
+ const PENDING_COLOR = \"#ffffff\";
+ ~~~~~
    + CategoryInfo          : ObjectNotFound: (const:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client> type MenuState = { latlng: LatLng };
Get-Content : A positional parameter cannot be found that accepts argument '='.
At line:1 char:1
+ type MenuState = { latlng: LatLng };
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : InvalidArgument: (:) [Get-Content], ParameterBindingException
    + FullyQualifiedErrorId : PositionalParameterNotFound,Microsoft.PowerShell.Commands.GetContentCommand

PS H:\Dokumenter\GitHub\dcs-retribution2\client> type RouteState =
Get-Content : A positional parameter cannot be found that accepts argument '='.
At line:1 char:1
+ type RouteState =
+ ~~~~~~~~~~~~~~~~~
    + CategoryInfo          : InvalidArgument: (:) [Get-Content], ParameterBindingException
    + FullyQualifiedErrorId : PositionalParameterNotFound,Microsoft.PowerShell.Commands.GetContentCommand

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   | { step: \"start\"; latlng: LatLng }
At line:1 char:3
+   | { step: \"start\"; latlng: LatLng }
+   ~
An empty pipe element is not allowed.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : EmptyPipeElement

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   | { step: \"end\"; start: LatLng; end: LatLng; name: string };
At line:1 char:3
+   | { step: \"end\"; start: LatLng; end: LatLng; name: string };
+   ~
An empty pipe element is not allowed.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : EmptyPipeElement

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client> function MapRightClickHandler() {
>>   const dispatch = useAppDispatch();
>>   const [menu, setMenu] = useState<MenuState | null>(null);
>>   const [route, setRoute] = useState<RouteState | null>(null);
>>
>>   useMapEvents({
>>     contextmenu(e) {
>>       e.originalEvent.preventDefault();
>>       if (route?.step === \"start\") {
>>         setRoute({ step: \"end\", start: route.latlng, end: e.latlng, name: \"\" });
>>         return;
>>       }
>>       setMenu({ latlng: e.latlng });
>>     },
>>     click() {
>>       if (route?.step === \"start\") setRoute(null);
>>       setMenu(null);
>>     },
>>   });
>>
>>   if (menu && !route) {
>>     const onAddDropZone = async () => {
>>       setMenu(null);
>>       await fetch(`${serverBase()}/qt/open-drop-zone-dialog`, {
>>         method: \"POST\",
>>         headers: { \"Content-Type\": \"application/json\" },
>>         body: JSON.stringify({ lat: menu.latlng.lat, lng: menu.latlng.lng }),
>>       });
>>     };
>>     const onAddConvoyRoute = () => {
>>       setRoute({ step: \"start\", latlng: menu.latlng });
>>       setMenu(null);
>>     };
>>     return (
>>       <Popup position={menu.latlng} eventHandlers={{ remove: () => setMenu(null) }} closeButton={false}>
>>         <div style={menuWrap}>
>>           <button style={menuItem} onMouseEnter={(e) => (e.currentTarget.style.background = \"#2c3e50\")} onMouseLeave={(e) => (e.currentTarget.style.background = \"transparent\")} onClick={onAddDropZone}>
>>             🎯 Add Drop Zone
>>           </button>
>>           <div style={menuDivider} />
>>           <button style={menuItem} onMouseEnter={(e) => (e.currentTarget.style.background = \"#2c3e50\")} onMouseLeave={(e) => (e.currentTarget.style.background = \"transparent\")} onClick={onAddConvoyRoute}>
>>             🚛 Add Convoy Route
>>           </button>
>>         </div>
>>       </Popup>
>>     );
At line:2 char:35
+   const dispatch = useAppDispatch();
+                                   ~
An expression was expected after '('.
At line:8 char:38
+       e.originalEvent.preventDefault();
+                                      ~
An expression was expected after '('.
At line:15 char:11
+     click() {
+           ~
An expression was expected after '('.
At line:16 char:36
+       if (route?.step === \"start\") setRoute(null);
+                                    ~
Missing statement block after if ( condition ).
At line:18 char:7
+     },
+       ~
Missing expression after ',' in pipeline element.
At line:21 char:12
+   if (menu && !route) {
+            ~~
The token '&&' is not a valid statement separator in this version.
At line:22 char:34
+     const onAddDropZone = async () => {
+                                  ~
An expression was expected after '('.
At line:24 char:33
+       await fetch(`${serverBase()}/qt/open-drop-zone-dialog`, {
+                                 ~
An expression was expected after '('.
At line:27 char:78
+ ... body: JSON.stringify({ lat: menu.latlng.lat, lng: menu.latlng.lng }),
+                                                                          ~
Missing expression after ',' in pipeline element.
At line:30 char:31
+     const onAddConvoyRoute = () => {
+                               ~
An expression was expected after '('.
Not all parse errors were reported.  Correct the reported errors and try again.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : ExpectedExpression

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   }
At line:1 char:3
+   }
+   ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client>   if (route?.step === \"start\") {
>>     return (
>>       <CircleMarker center={route.latlng} radius={8} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
>>         <Tooltip permanent direction=\"top\" offset={[0, -12]}>Route start — right-click to set end point</Tooltip>
>>       </CircleMarker>
>>     );
At line:3 char:148
+ ... DING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
+                                                                          ~
Missing file specification after redirection operator.
At line:3 char:148
+ ... DING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
+                                                                          ~
Missing closing ')' in expression.
At line:4 char:9
+         <Tooltip permanent direction=\"top\" offset={[0, -12]}>Route  ...
+         ~
The '<' operator is reserved for future use.
At line:4 char:18
+         <Tooltip permanent direction=\"top\" offset={[0, -12]}>Route  ...
+                  ~~~~~~~~~
Unexpected token 'permanent' in expression or statement.
At line:4 char:55
+         <Tooltip permanent direction=\"top\" offset={[0, -12]}>Route  ...
+                                                       ~
Missing type name after '['.
At line:4 char:56
+         <Tooltip permanent direction=\"top\" offset={[0, -12]}>Route  ...
+                                                        ~
Missing argument in parameter list.
At line:1 char:34
+   if (route?.step === \"start\") {
+                                  ~
Missing closing '}' in statement block or type definition.
At line:6 char:5
+     );
+     ~
Unexpected token ')' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : MissingFileSpecification

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   }
At line:1 char:3
+   }
+   ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client>   if (route?.step === \"end\") {
>>     const confirm = () => {
>>       dispatch(createConvoyRoute({ name: route.name.trim() || \"Convoy Route\", start_lat: route.start.lat, start_lng: route.start.lng, end_lat: route.end.lat, end_lng: route.end.lng }));
>>       setRoute(null);
>>     };
>>     return (
>>       <>
>>         <Polyline positions={[route.start, route.end]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: \"6 4\", opacity: 0.7 }} />
>>         <CircleMarker center={route.start} radius={6} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
>>         <Popup position={route.end} eventHandlers={{ remove: () => setRoute(null) }}>
>>           <div style={popupWrap}>
>>             <strong style={{ fontSize: 13 }}>🚛 New Convoy Route</strong>
>>             <input autoFocus style={inputStyle} placeholder=\"Route name (e.g. MSR Alpha)\" value={route.name} onChange={(e) => setRoute({ ...route, name: e.target.value })} onKeyDown={(e) => e.key === \"Enter\" && confirm()} />
>>             <div style={{ display: \"flex\", gap: 6, marginTop: 8 }}>
>>               <button style={btn} onClick={confirm}>✔ Create</button>
>>               <button style={{ ...btn, background: \"#555\" }} onClick={() => setRoute(null)}>Cancel</button>
>>             </div>
>>           </div>
>>         </Popup>
>>       </>
>>     );
At line:2 char:22
+     const confirm = () => {
+                      ~
An expression was expected after '('.
At line:3 char:58
+       dispatch(createConvoyRoute({ name: route.name.trim() || \"Convo ...
+                                                          ~
An expression was expected after '('.
At line:3 char:60
+       dispatch(createConvoyRoute({ name: route.name.trim() || \"Convo ...
+                                                            ~~
The token '||' is not a valid statement separator in this version.
At line:3 char:79
+ ... ateConvoyRoute({ name: route.name.trim() || \"Convoy Route\", start_l ...
+                                                                 ~
Missing argument in parameter list.
At line:7 char:9
+       <>
+         ~
Missing file specification after redirection operator.
At line:7 char:9
+       <>
+         ~
Missing closing ')' in expression.
At line:8 char:9
+         <Polyline positions={[route.start, route.end]} pathOptions={{ ...
+         ~
The '<' operator is reserved for future use.
At line:8 char:19
+         <Polyline positions={[route.start, route.end]} pathOptions={{ ...
+                   ~~~~~~~~~~
Unexpected token 'positions=' in expression or statement.
At line:10 char:63
+ ...        <Popup position={route.end} eventHandlers={{ remove: () => set ...
+                                                                  ~
An expression was expected after '('.
At line:10 char:86
+ ... osition={route.end} eventHandlers={{ remove: () => setRoute(null) }}>
+                                                                          ~
Missing file specification after redirection operator.
Not all parse errors were reported.  Correct the reported errors and try again.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : ExpectedExpression

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   }
At line:1 char:3
+   }
+   ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client>   return null;
null : The term 'null' is not recognized as the name of a cmdlet, function, script file, or operable program. Check
the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:10
+   return null;
+          ~~~~
    + CategoryInfo          : ObjectNotFound: (null:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client> }
At line:1 char:1
+ }
+ ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client> function DropZoneMarkers() {
>>   const dispatch = useAppDispatch();
>>   const zones = useAppSelector(selectDropZones);
>>   const openPackageDialog = async (dz: DropZone) => {
>>     await fetch(`${serverBase()}/qt/create-package/drop-zone/${dz.id}`, { method: \"POST\" });
>>   };
>>   return (
>>     <>
>>       {zones.map((dz) => (
>>         <CircleMarker key={dz.id} center={[dz.position.lat, dz.position.lng]} radius={11} pathOptions={{ color: \"#f5a623\", weight: 2, fillColor: \"#f5a623\", fillOpacity: 0.3 }}>
>>           <Popup>
>>             <div style={popupWrap}>
>>               <strong style={{ fontSize: 13 }}>🎯 {dz.name}</strong>
>>               <div style={{ fontSize: 11, color: \"#999\", margin: \"2px 0 8px\" }}>{dz.position.lat.toFixed(4)}, {dz.position.lng.toFixed(4)}</div>
>>               <button style={{ ...btn, width: \"100%\", marginBottom: 5 }} onClick={() => openPackageDialog(dz)}>📋 Create Mission</button>
>>               <button style={{ ...dangerBtn, width: \"100%\" }} onClick={() => dispatch(deleteDropZone(dz.id))}>🗑 Remove Drop Zone</button>
>>             </div>
>>           </Popup>
>>         </CircleMarker>
>>       ))}
At line:2 char:35
+   const dispatch = useAppDispatch();
+                                   ~
An expression was expected after '('.
At line:5 char:31
+     await fetch(`${serverBase()}/qt/create-package/drop-zone/${dz.id} ...
+                               ~
An expression was expected after '('.
At line:8 char:7
+     <>
+       ~
Missing file specification after redirection operator.
At line:8 char:7
+     <>
+       ~
Missing closing ')' in expression.
At line:9 char:7
+       {zones.map((dz) => (
+       ~
Unexpected token '{' in expression or statement.
At line:10 char:181
+ ...  \"#f5a623\", weight: 2, fillColor: \"#f5a623\", fillOpacity: 0.3 }}>
+                                                                          ~
Missing file specification after redirection operator.
At line:10 char:181
+ ...  \"#f5a623\", weight: 2, fillColor: \"#f5a623\", fillOpacity: 0.3 }}>
+                                                                          ~
Missing closing ')' in expression.
At line:11 char:11
+           <Popup>
+           ~
The '<' operator is reserved for future use.
At line:11 char:18
+           <Popup>
+                  ~
Missing closing ')' in expression.
At line:12 char:13
+             <div style={popupWrap}>
+             ~
The '<' operator is reserved for future use.
Not all parse errors were reported.  Correct the reported errors and try again.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : ExpectedExpression

PS H:\Dokumenter\GitHub\dcs-retribution2\client>     </>
< : The term '<' is not recognized as the name of a cmdlet, function, script file, or operable program. Check the
spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:5
+     </>
+     ~
    + CategoryInfo          : ObjectNotFound: (<:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   );
At line:1 char:3
+   );
+   ~
Unexpected token ')' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client> }
At line:1 char:1
+ }
+ ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client> function ConvoyRouteMarkers() {
>>   const dispatch = useAppDispatch();
>>   const routes = useAppSelector(selectConvoyRoutes);
>>   const openEscortDialog = async (route: ConvoyRoute) => {
>>     await fetch(`${serverBase()}/qt/create-package/convoy-route/${route.id}`, { method: \"POST\" });
>>   };
>>   return (
>>     <>
>>       {routes.map((r) => {
>>         const start: [number, number] = [r.start.lat, r.start.lng];
>>         const end: [number, number] = [r.end.lat, r.end.lng];
>>         return (
>>           <React.Fragment key={r.id}>
>>             <Polyline positions={[start, end]} pathOptions={{ color: ROUTE_COLOR, weight: 3, dashArray: \"8 5\", opacity: 0.85 }}>
>>               <Tooltip sticky>{r.name}</Tooltip>
>>             </Polyline>
>>             <CircleMarker center={start} radius={7} pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.9, weight: 2 }}>
>>               <Popup>
>>                 <div style={popupWrap}>
>>                   <strong style={{ fontSize: 13 }}>🚛 {r.name}</strong>
>>                   <div style={{ fontSize: 11, color: \"#999\", margin: \"2px 0 8px\" }}>Start: {r.start.lat.toFixed(4)}, {r.start.lng.toFixed(4)}<br />End: {r.end.lat.toFixed(4)}, {r.end.lng.toFixed(4)}</div>
>>                   <button style={{ ...btn, width: \"100%\", marginBottom: 5 }} onClick={() => openEscortDialog(r)}>✈ Plan Escort Mission</button>
>>                   <button style={{ ...dangerBtn, width: \"100%\" }} onClick={() => dispatch(deleteConvoyRoute(r.id))}>🗑 Remove Route</button>
>>                 </div>
>>               </Popup>
>>             </CircleMarker>
>>             <CircleMarker center={end} radius={5} pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.7, weight: 2 }} />
>>           </React.Fragment>
>>         );
>>       })}
At line:2 char:35
+   const dispatch = useAppDispatch();
+                                   ~
An expression was expected after '('.
At line:5 char:31
+     await fetch(`${serverBase()}/qt/create-package/convoy-route/${rou ...
+                               ~
An expression was expected after '('.
At line:8 char:7
+     <>
+       ~
Missing file specification after redirection operator.
At line:8 char:7
+     <>
+       ~
Missing closing ')' in expression.
At line:9 char:7
+       {routes.map((r) => {
+       ~
Unexpected token '{' in expression or statement.
At line:13 char:38
+           <React.Fragment key={r.id}>
+                                      ~
Missing file specification after redirection operator.
At line:13 char:38
+           <React.Fragment key={r.id}>
+                                      ~
Missing closing ')' in expression.
At line:14 char:13
+             <Polyline positions={[start, end]} pathOptions={{ color:  ...
+             ~
The '<' operator is reserved for future use.
At line:14 char:23
+             <Polyline positions={[start, end]} pathOptions={{ color:  ...
+                       ~~~~~~~~~~
Unexpected token 'positions=' in expression or statement.
At line:14 char:131
+ ...  color: ROUTE_COLOR, weight: 3, dashArray: \"8 5\", opacity: 0.85 }}>
+                                                                          ~
Missing file specification after redirection operator.
Not all parse errors were reported.  Correct the reported errors and try again.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : ExpectedExpression

PS H:\Dokumenter\GitHub\dcs-retribution2\client>     </>
< : The term '<' is not recognized as the name of a cmdlet, function, script file, or operable program. Check the
spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:5
+     </>
+     ~
    + CategoryInfo          : ObjectNotFound: (<:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

PS H:\Dokumenter\GitHub\dcs-retribution2\client>   );
At line:1 char:3
+   );
+   ~
Unexpected token ')' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client> }
At line:1 char:1
+ }
+ ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client>
PS H:\Dokumenter\GitHub\dcs-retribution2\client> export default function DropZoneLayer() {
>>   return (
>>     <>
>>       <DropZoneMarkers />
>>       <ConvoyRouteMarkers />
>>       <MapRightClickHandler />
>>     </>
>>   );
At line:1 char:39
+ export default function DropZoneLayer() {
+                                       ~
An expression was expected after '('.
At line:3 char:7
+     <>
+       ~
Missing file specification after redirection operator.
At line:3 char:7
+     <>
+       ~
Missing closing ')' in expression.
At line:4 char:7
+       <DropZoneMarkers />
+       ~
The '<' operator is reserved for future use.
At line:4 char:24
+       <DropZoneMarkers />
+                        ~~
Unexpected token '/>' in expression or statement.
At line:1 char:41
+ export default function DropZoneLayer() {
+                                         ~
Missing closing '}' in statement block or type definition.
At line:8 char:3
+   );
+   ~
Unexpected token ')' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : ExpectedExpression

PS H:\Dokumenter\GitHub\dcs-retribution2\client> }
At line:1 char:1
+ }
+ ~
Unexpected token '}' in expression or statement.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : UnexpectedToken

PS H:\Dokumenter\GitHub\dcs-retribution2\client> ''')
>> content.close()
>> print('done')
>> "









