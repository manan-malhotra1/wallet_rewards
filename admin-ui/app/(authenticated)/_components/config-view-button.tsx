/**
 * "View" affordance for a live config row (Epic 25 / Task 9). Opens a
 * read-only drawer rendering the config via the shared `ConfigDetail`. Reused
 * by the pricing / commission / tax / limit tables.
 */
"use client";

import * as React from "react";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import type { ConfigType } from "@/lib/api-types";

export function ConfigViewButton({
  configType,
  data,
  title,
}: {
  configType: ConfigType;
  data: Record<string, unknown>;
  title: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        View
      </Button>
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>{title}</DrawerTitle>
          </DrawerHeader>
          <DrawerBody>
            <ConfigDetail configType={configType} data={data} />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </>
  );
}
