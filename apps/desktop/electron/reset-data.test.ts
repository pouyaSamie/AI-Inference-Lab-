import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { confirmLocalReset, resetManagedData } from "./reset-data";

let root:string;
beforeEach(async()=>{root=await fs.mkdtemp(path.join(os.tmpdir(),'lab-reset-test-'));await fs.mkdir(path.join(root,'local-lab/managed-engines'),{recursive:true});});
afterEach(async()=>{await fs.rm(root,{recursive:true,force:true});});
const put=async(file:string,value='retained bytes')=>{await fs.mkdir(path.dirname(path.join(root,file)),{recursive:true});await fs.writeFile(path.join(root,file),value);};
it('stops first, preserves engines and unknown files, and moves all lab records together to recoverable Trash',async()=>{
  await put('local-lab/controller.sqlite3');await put('local-lab/optuna.sqlite3');await put('local-lab/worker/hash-cache.json');
  await put('local-lab/managed-engines/llama-server','engine');await put('local-lab/manual-model.gguf','model');await put('operator-token.bin');
  const calls:string[]=[];
  const trash=vi.fn(async(folder:string)=>{calls.push('trash');expect(await fs.readFile(path.join(folder,'local-lab/controller.sqlite3'),'utf8')).toBe('retained bytes');await fs.rename(folder,path.join(root,'test-trash'));});
  await resetManagedData({userData:root,protectedPaths:[path.join(root,'local-lab/managed-engines')],stop:async()=>{calls.push('stop');},clearBrowserData:async()=>{calls.push('clear');},trash});
  expect(calls).toEqual(['stop','clear','trash']);expect(await fs.readFile(path.join(root,'local-lab/managed-engines/llama-server'),'utf8')).toBe('engine');
  expect(await fs.readFile(path.join(root,'local-lab/manual-model.gguf'),'utf8')).toBe('model');
  await expect(fs.stat(path.join(root,'local-lab/controller.sqlite3'))).rejects.toMatchObject({code:'ENOENT'});
  expect(await fs.readFile(path.join(root,'test-trash/local-lab/optuna.sqlite3'),'utf8')).toBe('retained bytes');
});
it('restores both stores and configuration if Trash is unavailable',async()=>{
  for(const file of ['controller.sqlite3','optuna.sqlite3','config.json'])await put('local-lab/'+file);
  await expect(resetManagedData({userData:root,protectedPaths:[],stop:async()=>{},clearBrowserData:async()=>{},trash:async()=>{throw Error('Trash unavailable');}})).rejects.toThrow('Trash unavailable');
  for(const file of ['controller.sqlite3','optuna.sqlite3','config.json'])expect(await fs.readFile(path.join(root,'local-lab',file),'utf8')).toBe('retained bytes');
});
it('refuses overlapping model roots and symlinked stores before stopping services',async()=>{
  await put('local-lab/controller.sqlite3');const stop=vi.fn(async()=>{});
  const options={userData:root,protectedPaths:[path.join(root,'local-lab')],stop,clearBrowserData:async()=>{},trash:async()=>{}};
  await expect(resetManagedData(options)).rejects.toThrow('overlaps');expect(stop).not.toHaveBeenCalled();
  await fs.unlink(path.join(root,'local-lab/controller.sqlite3'));await put('external-db');await fs.symlink(path.join(root,'external-db'),path.join(root,'local-lab/controller.sqlite3'));
  await expect(resetManagedData({...options,protectedPaths:[]})).rejects.toThrow('symlinked');expect(stop).not.toHaveBeenCalled();
  expect(await fs.readFile(path.join(root,'external-db'),'utf8')).toBe('retained bytes');
});
it('does not move any store when shutdown fails',async()=>{
  await put('local-lab/controller.sqlite3');const trash=vi.fn();
  await expect(resetManagedData({userData:root,protectedPaths:[],stop:async()=>{throw Error('Shutdown still running');},clearBrowserData:async()=>{},trash})).rejects.toThrow('Shutdown still running');
  expect(trash).not.toHaveBeenCalled();expect(await fs.readFile(path.join(root,'local-lab/controller.sqlite3'),'utf8')).toBe('retained bytes');
});

it('native cancellation never resets data and activity is rechecked after confirmation',async()=>{
  const reset=vi.fn(async()=>{}),assertIdle=vi.fn(async()=>{});
  expect(await confirmLocalReset({assertIdle,confirm:async()=>false,reset})).toEqual({canceled:true});expect(reset).not.toHaveBeenCalled();
  assertIdle.mockReset();assertIdle.mockResolvedValueOnce(undefined).mockRejectedValueOnce(Error('A job started'));
  await expect(confirmLocalReset({assertIdle,confirm:async()=>true,reset})).rejects.toThrow('A job started');expect(reset).not.toHaveBeenCalled();
});
