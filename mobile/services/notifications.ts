/**
 * 通知服务
 * 处理本地推送通知
 */
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';

// 配置通知处理
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

class NotificationService {
  private isReady = false;

  /**
   * 初始化通知服务
   */
  async initialize(): Promise<boolean> {
    if (this.isReady) return true;

    if (!Device.isDevice) {
      console.log('通知功能仅在真机上可用');
      return false;
    }

    try {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }

      if (finalStatus !== 'granted') {
        console.log('未获取通知权限');
        return false;
      }

      // Android 需要设置通知渠道
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('daily-report', {
          name: '每日报告',
          importance: Notifications.AndroidImportance.MAX,
          vibrationPattern: [0, 250, 250, 250],
          lightColor: '#6C63FF',
        });
      }

      this.isReady = true;
      return true;
    } catch (error) {
      console.error('初始化通知失败:', error);
      return false;
    }
  }

  /**
   * 发送本地通知
   */
  async sendLocalNotification(
    title: string,
    body: string,
    data?: Record<string, string>
  ): Promise<string | null> {
    try {
      const id = await Notifications.scheduleNotificationAsync({
        content: {
          title,
          body,
          data: data || {},
          sound: true,
        },
        trigger: null, // 立即发送
      });
      return id;
    } catch (error) {
      console.error('发送通知失败:', error);
      return null;
    }
  }

  /**
   * 安排每日报告通知
   */
  async scheduleDailyReportNotification(
    hour: number,
    minute: number
  ): Promise<string | null> {
    try {
      // 先取消之前的定时通知
      await this.cancelAllScheduledNotifications();

      const id = await Notifications.scheduleNotificationAsync({
        content: {
          title: '📊 今日财经日报已更新',
          body: '点击查看今日市场分析和投资建议',
          data: { type: 'daily_report' },
          sound: true,
        },
        trigger: {
          hour,
          minute,
          repeats: true,
        },
      });

      console.log(`已安排每日 ${hour}:${minute} 的报告通知`);
      return id;
    } catch (error) {
      console.error('安排定时通知失败:', error);
      return null;
    }
  }

  /**
   * 取消所有定时通知
   */
  async cancelAllScheduledNotifications(): Promise<void> {
    try {
      await Notifications.cancelAllScheduledNotificationsAsync();
    } catch (error) {
      console.error('取消定时通知失败:', error);
    }
  }

  /**
   * 获取所有已安排的通知
   */
  async getScheduledNotifications(): Promise<Notifications.NotificationRequest[]> {
    try {
      return await Notifications.getAllScheduledNotificationsAsync();
    } catch (error) {
      console.error('获取定时通知列表失败:', error);
      return [];
    }
  }

  /**
   * 添加通知响应监听器
   */
  addNotificationResponseListener(
    callback: (response: Notifications.NotificationResponse) => void
  ): Notifications.Subscription {
    return Notifications.addNotificationResponseReceivedListener(callback);
  }

  /**
   * 添加前台通知监听器
   */
  addNotificationReceivedListener(
    callback: (notification: Notifications.Notification) => void
  ): Notifications.Subscription {
    return Notifications.addNotificationReceivedListener(callback);
  }
}

// 导出单例实例
export const notificationService = new NotificationService();

// 导出类（用于自定义实例）
export { NotificationService };
