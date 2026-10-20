import { firefox, type LaunchOptions } from '@playwright/test';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

/** macOS 27: keep test Firefox app data separate from the user's TCC-protected
 * Firefox directory. No sandbox, signature, or privacy permission is changed.
 * https://github.com/microsoft/playwright/issues/42768
 */
export function isolatedFirefox(): LaunchOptions {
  if (process.platform !== 'darwin' || Number(os.release().split('.')[0]) < 26) return {timeout:30_000};
  const executable = firefox.executablePath();
  const resources = path.resolve(path.dirname(executable),'../Resources');
  const ini = path.join(resources,'browser/rift-test-application.ini');
  const original = readFileSync(path.join(resources,'application.ini'),'utf8');
  writeFileSync(ini,original.replace(/^Vendor=Mozilla$/m,'Vendor=RIFTTesting').replace(/^Name=Firefox$/m,'Name=RIFTPlaywright'));
  const directory=path.resolve('../build/browser-tests/firefox-launch');mkdirSync(directory,{recursive:true});
  const wrapper=path.join(directory,'firefox');
  const quote=(v:string)=>"'"+v.replaceAll("'","'\\''")+"'";
  writeFileSync(wrapper,`#!/bin/sh\nexec ${quote(executable)} -app ${quote(ini)} "$@"\n`,{mode:0o755});
  return {executablePath:wrapper,timeout:30_000};
}
