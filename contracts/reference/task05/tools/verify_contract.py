#!/usr/bin/env python3
"""TASK-05 reconstructed reference verifier: schema and fixture-level semantics only.
Does NOT establish runtime ARP, forwarding, causality, backend trust or snapshot topology validity.
"""
from pathlib import Path
import json,copy,sys,hashlib
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
SC=json.loads((ROOT/'schemas/task05-contract-v1.schema.json').read_text())
Draft202012Validator.check_schema(SC)
V=Draft202012Validator(SC)

def sem(o):
 err=[]
 def need(v,label):
  if not v:err.append(label)
 if 'snapshot_ref' in o and o['snapshot_ref'] is not None:
  s=o['snapshot_ref'];need(s['project_id']==o['project_id'],'snapshot-project');need(s['base_simulation_revision']<=s['base_state_revision'],'snapshot-revisions')
 if 'request_results' not in o:return err
 rr=o['request_results']; stats=o['statistics'];events=o['events'];diag=o['diagnostics'];hops=o['hop_evidence'];
 need(o['started_at_ns']<=o['finalized_at_ns']<=o['closed_at_ns'],'test-time-order')
 need([x['sequence'] for x in rr]==list(range(1,len(rr)+1)),'sequence-order')
 need(len(rr)==stats['requests_started'],'started-count')
 need(stats['requests_planned']==4,'planned-count')
 need(len({x['icmp_identifier'] for x in rr})<=1,'icmp-identifier')
 need(o['execution_status']=='INCOMPLETE' or (len(rr)==4 and all(x['outcome']!='EXECUTION_LIMITED' for x in rr)),'complete-4')
 need(o['execution_status']!='INCOMPLETE' or (o['aggregate_outcome'] is None and o['observation_status']=='NOT_STARTED'),'incomplete-outcome')
 matched=sum(x['outcome']=='SUCCESS' for x in rr)
 if o['execution_status']=='COMPLETED':need(o['aggregate_outcome']==('SUCCESS' if matched==4 else 'PARTIAL_SUCCESS' if matched else 'FAILURE'),'aggregate')
 need(stats['replies_received']==matched,'matched-counter')
 emitted=sum(x['echo_request_emitted_at_ns'] is not None for x in rr)
 need(stats['requests_sent']==emitted,'sent-counter')
 need(stats['lost_sent_requests']==emitted-matched,'lost-counter')
 lp=None if emitted==0 else (2*10000*(emitted-matched)//emitted+1)//2
 need(stats['loss_percentage_hundredths']==lp,'loss-percentage')
 rtts=[x['rtt_ns'] for x in rr if x['outcome']=='SUCCESS']
 need(stats['rtt_min_ns']==(min(rtts) if rtts else None),'rtt-min')
 need(stats['rtt_max_ns']==(max(rtts) if rtts else None),'rtt-max')
 need(stats['rtt_sum_ns']==(sum(rtts) if rtts else None),'rtt-sum')
 need(stats['rtt_avg_ns_rounded']==((2*sum(rtts)//len(rtts)+1)//2 if rtts else None),'rtt-avg')
 ids=[e['event_id'] for e in events]; dids=[d['diagnostic_id'] for d in diag]; hi=[h['hop_id'] for h in hops]
 need(len(ids)==len(set(ids)),'duplicate-event-id');need(len(dids)==len(set(dids)),'duplicate-diagnostic-id');need(len(hi)==len(set(hi)),'duplicate-hop-id')
 need(len({e['execution_index'] for e in events})==len(events),'duplicate-exec-index')
 need(len({e['creation_sequence'] for e in events})==len(events),'duplicate-create-seq')
 need(all(events[i]['execution_index']<events[i+1]['execution_index'] and events[i]['virtual_time_ns']<=events[i+1]['virtual_time_ns'] for i in range(len(events)-1)),'event-execution-order')
 need(len(events)<=40000,'event-budget')
 primary_by_seq={}
 for d in diag:
  if d['trigger_event_id'] is not None:need(d['trigger_event_id'] in ids,'diag-trigger-reference')
  if d['is_primary']:
   need(d['request_sequence'] is not None,'primary-request-correlation')
   primary_by_seq[d['request_sequence']]=primary_by_seq.get(d['request_sequence'],0)+1
 need(all(v<=1 for v in primary_by_seq.values()),'multiple-primary')
 for i,x in enumerate(rr):
  need(x['deadline_at_ns']==x['started_at_ns']+1000000000,'deadline')
  need(x['started_at_ns']<=x['finalized_at_ns']<=x['deadline_at_ns'],'request-time')
  if i:need(rr[i-1]['finalized_at_ns']<=x['started_at_ns'],'attempt-nonoverlap')
  if x['echo_request_emitted_at_ns'] is not None:need(x['started_at_ns']<=x['echo_request_emitted_at_ns']<=x['finalized_at_ns'],'emission-time')
  if x['outcome']=='SUCCESS':
   need(x['matched_reply_event_id'] in ids,'match-reference')
   ms=[e for e in events if e['event_id']==x['matched_reply_event_id']]
   if ms:
    m=ms[0];need(m['kind']=='ICMP_ECHO_MATCHED' and m['request_sequence']==x['sequence'],'match-event-kind-seq')
    need(m['virtual_time_ns']==x['finalized_at_ns'],'match-time')
   need(x['echo_request_emitted_at_ns'] is not None and x['rtt_ns']==x['finalized_at_ns']-x['echo_request_emitted_at_ns'],'rtt-derivation')
   need(x['primary_diagnostic_id'] is None,'success-no-primary')
  else:need(x['matched_reply_event_id'] is None and x['rtt_ns'] is None,'nonsuccess-no-match')
  if x['primary_diagnostic_id'] is not None:
   match=[d for d in diag if d['diagnostic_id']==x['primary_diagnostic_id']]
   need(len(match)==1 and match[0]['is_primary'] and match[0]['request_sequence']==x['sequence'],'primary-reference')
 need(len([x['matched_reply_event_id'] for x in rr if x['matched_reply_event_id'] is not None])==len(set(x['matched_reply_event_id'] for x in rr if x['matched_reply_event_id'] is not None)),'duplicate-matched-reply')
 for h in hops:
  need(all(x in ids for x in h['source_event_ids']),'hop-event-reference')
  need(h['drop_diagnostic_id'] is None or h['drop_diagnostic_id'] in dids,'hop-diag-reference')
  need(h['outcome']!='DELIVERED' or (h['rx_complete_ns'] is not None and h['rx_complete_ns']>=h['tx_start_ns']),'delivered-time')
  need(h['outcome']!='DROPPED' or h['drop_diagnostic_id'] is not None,'drop-cause')
  need(h['direction']!='LOCAL','physical-hop-local')
 if o['source_device_id']==o['destination_device_id']:need(not hops,'self-ping-no-hops')
 return err

def check(o):
 se=list(V.iter_errors(o));return ([f'SCHEMA:{e.message[:80]}' for e in se] if se else sem(o))

def run():
 passed=failed=0;results=[]
 def record(id,expected,errors):
  nonlocal passed,failed
  okay=(not errors) if expected else bool(errors)
  passed+=int(okay);failed+=int(not okay)
  results.append({'test_id':id,'expected':'ACCEPT' if expected else 'REJECT','status':'PASS' if okay else 'FAIL','reason':errors[:3]})
 ex={x.stem:json.loads(x.read_text()) for x in sorted((ROOT/'examples').glob('*.json'))}
 for n,v in ex.items():record('positive:'+n,True,check(v))
 def neg(n,source,modify):
  obj=copy.deepcopy(ex[source]);modify(obj);record('negative:'+n,False,check(obj))
 neg('unsupported_version','ping_command',lambda x:x.update(contract_version='2.0.0'))
 neg('unknown_field','ping_command',lambda x:x.update(invented_route='x'))
 neg('bad_uuid','ping_command',lambda x:x.update(source_device_id='bad'))
 neg('bad_snapshot_digest_format','ping_command',lambda x:x['snapshot_ref'].update(configuration_digest='bad'))
 neg('snapshot_project_mismatch','ping_command',lambda x:x['snapshot_ref'].update(project_id='019a5000-0000-7000-8000-000000000999'))
 neg('negative_time','ping_success',lambda x:x.update(started_at_ns=-1))
 neg('fractional_ns','ping_success',lambda x:x['request_results'][0].update(started_at_ns=0.1))
 neg('invalid_event_phase','ping_success',lambda x:x['events'][0].update(phase=99))
 neg('bad_aggregate','ping_success',lambda x:x.update(aggregate_outcome='FAILURE'))
 neg('bad_started_count','ping_success',lambda x:x['statistics'].update(requests_started=3))
 neg('bad_sent_counter','ping_success',lambda x:x['statistics'].update(requests_sent=3))
 neg('bad_loss','ping_partial_success',lambda x:x['statistics'].update(loss_percentage_hundredths=20))
 neg('zero_sent_loss_nonnull','ping_failure_zero_sent',lambda x:x['statistics'].update(loss_percentage_hundredths=10000))
 neg('bad_rtt','ping_success',lambda x:x['request_results'][0].update(rtt_ns=9))
 neg('missing_match_event','ping_success',lambda x:x['events'].pop(0))
 neg('duplicate_match','ping_success',lambda x:x['request_results'][1].update(matched_reply_event_id='ev-match-1'))
 neg('ghost_sequence','ping_incomplete_safety',lambda x:x['request_results'].append(copy.deepcopy(ex['ping_success']['request_results'][2])))
 neg('incomplete_aggregate','ping_incomplete_safety',lambda x:x.update(aggregate_outcome='PARTIAL_SUCCESS'))
 neg('incomplete_observation','ping_incomplete_safety',lambda x:x.update(observation_status='COMPLETE'))
 neg('nonconsecutive_sequence','ping_success',lambda x:x['request_results'][1].update(sequence=4))
 neg('incorrect_deadline','ping_success',lambda x:x['request_results'][0].update(deadline_at_ns=999))
 neg('overlap_attempts','ping_success',lambda x:x['request_results'][1].update(started_at_ns=0,deadline_at_ns=1000000000))
 neg('two_primary','ping_failure_no_arp',lambda x:x['diagnostics'].append(dict(x['diagnostics'][0],diagnostic_id='extra-d')))
 neg('missing_primary_reference','ping_failure_no_arp',lambda x:x['request_results'][0].update(primary_diagnostic_id='missing'))
 neg('bad_diagnostic_code','ping_failure_no_arp',lambda x:x['diagnostics'][0].update(code='INVENTED_FAILURE'))
 neg('missing_diag_trigger','ping_failure_no_arp',lambda x:x['diagnostics'][0].update(trigger_event_id='missing-event'))
 neg('out_of_order_events','ping_success',lambda x:x['events'][0].update(execution_index=9999))
 neg('duplicate_event_id','ping_success',lambda x:x['events'][1].update(event_id=x['events'][0]['event_id']))
 neg('invalid_event_kind','ping_success',lambda x:x['events'][0].update(kind='INVENTED_PACKET_TELEPORT'))
 neg('completed_only_three','ping_success',lambda x:x['request_results'].pop())
 neg('result_snapshot_mismatch','ping_success',lambda x:x['snapshot_ref'].update(project_id='019a5000-0000-7000-8000-000000000999'))
 neg('bad_error_code','invalid_request',lambda x:x.update(code='FAKE_UNKNOWN_ERROR'))
 neg('error_unexpected_results','invalid_request',lambda x:x.update(request_results=[]))
 neg('self_ping_phantom_hop','ping_self_local',lambda x:x['hop_evidence'].append(dict(hop_id='h1',packet_id='p1',frame_id='f1',request_sequence=1,direction='FORWARD',from_device_id=x['source_device_id'],to_device_id=x['source_device_id'],egress_interface_id='019a5000-0000-7000-8000-000000000006',ingress_interface_id='019a5000-0000-7000-8000-000000000007',connection_id='019a5000-0000-7000-8000-000000000005',tx_start_ns=100000,rx_complete_ns=200000,outcome='DELIVERED',drop_diagnostic_id=None,source_event_ids=['ev-match-1'])))
 neg('hop_missing_source_event','ping_success',lambda x:x['hop_evidence'].append(dict(hop_id='h1',packet_id='p1',frame_id='f1',request_sequence=1,direction='FORWARD',from_device_id=x['source_device_id'],to_device_id=x['destination_device_id'],egress_interface_id='019a5000-0000-7000-8000-000000000006',ingress_interface_id='019a5000-0000-7000-8000-000000000007',connection_id='019a5000-0000-7000-8000-000000000005',tx_start_ns=100000,rx_complete_ns=200000,outcome='DELIVERED',drop_diagnostic_id=None,source_event_ids=['not-real'])))
 neg('hop_drop_without_cause','ping_success',lambda x:x['hop_evidence'].append(dict(hop_id='h1',packet_id='p1',frame_id='f1',request_sequence=1,direction='FORWARD',from_device_id=x['source_device_id'],to_device_id=x['destination_device_id'],egress_interface_id='019a5000-0000-7000-8000-000000000006',ingress_interface_id='019a5000-0000-7000-8000-000000000007',connection_id='019a5000-0000-7000-8000-000000000005',tx_start_ns=100000,rx_complete_ns=None,outcome='DROPPED',drop_diagnostic_id=None,source_event_ids=['ev-match-1'])))
 neg('unsent_marked_success','ping_success',lambda x:x['request_results'][0].update(echo_request_emitted_at_ns=None))
 neg('bad_icmp_identifier','ping_success',lambda x:x['request_results'][1].update(icmp_identifier=777))
 neg('observation_tampered_outcome','ping_observation_truncated',lambda x:x.update(aggregate_outcome='FAILURE'))

 neg('wrong_error_class_for_code','invalid_request',lambda x:x.update(error_class='COMMAND_INVALID'))
 neg('frame_tx_missing_connection','ping_success',lambda x:x['events'][0].update(connection_id=None))
 neg('frame_tx_missing_egress','ping_success',lambda x:x['events'][0].update(egress_interface_id=None))
 neg('frame_arrival_missing_ingress','ping_success',lambda x:x['events'][1].update(ingress_interface_id=None))
 neg('frame_arrival_missing_frame_id','ping_success',lambda x:x['events'][1].update(frame_id=None))
 neg('unknown_evidence_fact','ping_success',lambda x:x['events'][0]['facts'].update(invented_route=True))
 neg('wrong_evidence_fact_type','ping_success',lambda x:x['events'][0]['facts'].update(ttl_before='sixteen'))
 neg('wrong_event_kind_case','ping_success',lambda x:x['events'][0].update(kind='frame_tx'))
 neg('invalid_warning_code','ping_success',lambda x:x['derived_warning_evidence'].append(dict(code='MADE_UP_WARNING',facts={})))
 report={'source':'RECONSTRUCTED REFERENCE; NOT original source bundle','positive_examples':len(ex),'negative_mutations':len(results)-len(ex),'passed':passed,'failed':failed,'results':results,'engine_tests_executed':0,'integration_tests_executed':0}
 (ROOT/'reports'/'contract_verification_results.json').write_text(json.dumps(report,indent=2)+'\n')
 print(f'Positive examples: {len(ex)}/{len(ex)} expected accepted; negative cases: {len(results)-len(ex)} expected rejected')
 print(f'TOTAL: {passed} PASS / {failed} FAIL')
 for t in results:
  if t['status']=='FAIL':print('FAIL:',t)
 return 1 if failed else 0
if __name__=='__main__':sys.exit(run())
